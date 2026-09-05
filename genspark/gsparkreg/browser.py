"""Chrome signup for Genspark.ai (pydoll) — Azure AD B2C email + image CAPTCHA + OTP.

Flow mirrors https://github.com/flupyxyz/genspark-farm:
homepage Sign up → More options → Sign up now → email + CAPTCHA → 6-digit
verify → password → #continue → optional Claim My Free Month (Stripe $0).
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from gsparkreg.captcha import solve_image_candidates
from gsparkreg.config import claim_free_month
from gsparkreg.log import log
from gsparkreg.paths import DATA, ROOT
from gsparkreg.stop import raise_if_stop

HOME = "https://www.genspark.ai/"
PRICING = "https://www.genspark.ai/me?open_pricing=pricing"
LOGIN_API = "https://www.genspark.ai/api/login?redirect_url=/"
APP_RE = re.compile(r"genspark\.ai/(?:agents|me|chat|slides|docs|super-agent)?(?:/|$|\?)", re.I)

# Walk main document + same-origin iframes (B2C often sits in a frame).
_WALK_PREAMBLE = r"""
  const walk = (fn) => {
    const seen = [];
    const go = (win) => {
      try {
        const r = fn(win.document, win);
        if (r !== undefined && r !== null && r !== '' && r !== 0 && r !== false) return r;
      } catch (e) {}
      let frames = [];
      try { frames = [...(win.frames || [])]; } catch (e) {}
      for (const f of frames) {
        try {
          const r = go(f);
          if (r !== undefined && r !== null && r !== '' && r !== 0 && r !== false) return r;
        } catch (e) {}
      }
      return null;
    };
    return go(window);
  };
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 4 && r.height > 4;
  };
  const labelOf = (el) => (el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').replace(/\s+/g,' ').trim();
  const setNative = (el, val) => {
    if (!el) return false;
    try { el.removeAttribute('disabled'); el.removeAttribute('aria-disabled'); el.disabled = false; } catch (e) {}
    el.focus();
    try { el.click(); } catch (e) {}
    const proto = el.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, val);
    else el.value = val;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    el.dispatchEvent(new Event('input', { bubbles: true }));
    try { el.dispatchEvent(new InputEvent('input', { bubbles: true, data: val, inputType: 'insertText' })); } catch (e) {}
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };
"""

CLICK_TEXT_JS = r"""
(() => {
""" + _WALK_PREAMBLE + r"""
  const wants = %WANTS%;
  const tags = %TAGS%;
  return walk((doc) => {
    const els = [...doc.querySelectorAll(tags)].filter(vis);
    for (const want of wants) {
      const w = String(want).toLowerCase();
      const exact = els.find(el => labelOf(el).toLowerCase() === w);
      if (exact) { exact.click(); return labelOf(exact).slice(0, 60); }
    }
    for (const want of wants) {
      const w = String(want).toLowerCase();
      const hit = els.find(el => {
        const t = labelOf(el).toLowerCase();
        return t && t.length < 80 && t.includes(w);
      });
      if (hit) { hit.click(); return labelOf(hit).slice(0, 60); }
    }
    return '';
  }) || '';
})()
"""

FILL_BY_PLACEHOLDER_JS = r"""
(() => {
""" + _WALK_PREAMBLE + r"""
  const val = %VAL%;
  const hints = %HINTS%;
  return walk((doc) => {
    const inputs = [...doc.querySelectorAll('input, textarea')].filter(vis);
    for (const h of hints) {
      const re = new RegExp(h, 'i');
      const el = inputs.find(i => re.test(
        (i.placeholder||'') + (i.name||'') + (i.id||'') + (i.type||'') +
        (i.getAttribute('aria-label')||'') + (i.autocomplete||'')
      ));
      if (el && setNative(el, val)) return (el.placeholder || el.name || el.id || 'ok').slice(0, 40);
    }
    return '';
  }) || '';
})()
"""

FILL_PASSWORDS_JS = r"""
(() => {
""" + _WALK_PREAMBLE + r"""
  const pwd = %VAL%;
  return walk((doc) => {
    const pwds = [...doc.querySelectorAll('input[type=password]')].filter(el => {
      try { el.removeAttribute('disabled'); el.removeAttribute('aria-disabled'); } catch (e) {}
      return vis(el) || el.getAttribute('type') === 'password';
    });
    let n = 0;
    for (const el of pwds.slice(0, 2)) {
      if (setNative(el, pwd)) n++;
    }
    return n;
  }) || 0;
})()
"""

CLICK_CONTINUE_JS = r"""
(() => {
""" + _WALK_PREAMBLE + r"""
  return walk((doc) => {
    const byId = doc.querySelector('#continue, button#continue, input#continue');
    if (byId) {
      try { byId.removeAttribute('disabled'); byId.removeAttribute('aria-disabled'); byId.disabled = false; } catch (e) {}
      byId.click();
      return 'id:continue';
    }
    const btns = [...doc.querySelectorAll('button, [type=submit], [role=button], a')].filter(vis);
    const prefer = ['create account', 'create', 'continue', 'sign up', 'next'];
    const deny = /google|apple|microsoft|github|facebook|more options|privacy|terms/;
    for (const want of prefer) {
      const hit = btns.find(el => {
        const t = labelOf(el).toLowerCase();
        return t && t.length < 40 && t.includes(want) && !deny.test(t);
      });
      if (hit) {
        try { hit.removeAttribute('disabled'); hit.disabled = false; } catch (e) {}
        hit.click();
        return labelOf(hit).slice(0, 50);
      }
    }
    return '';
  }) || '';
})()
"""

EXTRACT_CAPTCHA_JS = r"""
(() => {
  const grab = (img) => {
    if (!img) return '';
    const src = img.src || img.getAttribute('src') || img.currentSrc || '';
    if (src.startsWith('data:image') && src.length > 80) return src;
    if (img.naturalWidth > 10) {
      try {
        const c = document.createElement('canvas');
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        c.getContext('2d').drawImage(img, 0, 0);
        return c.toDataURL('image/png');
      } catch (e) {}
    }
    return '';
  };
  const byId = document.querySelector('#captchaControlChallengeCode-img, img[id*="captcha"]');
  const a = grab(byId);
  if (a) return a;
  for (const img of document.querySelectorAll('img')) {
    const s = grab(img);
    if (s && !/logo/i.test(img.id || '') && !/logo/i.test(img.className || '')) return s;
  }
  return '';
})()
"""

CLICK_ID_JS = r"""
(() => {
  const el = document.querySelector(%SEL%);
  if (!el) return '';
  try { el.removeAttribute('disabled'); el.disabled = false; } catch (e) {}
  el.click();
  return el.id || (el.innerText || '').trim().slice(0, 40) || 'ok';
})()
"""

# Ô email visible của form B2C — URL đổi sang local=signup TRƯỚC khi DOM render
# xong, nên "ready" phải căn vào input thật, không căn vào URL.
EMAIL_FIELD_JS = r"""
(() => {
  const cands = document.querySelectorAll('#email, input[type="email"], input[name="email"]');
  for (const el of cands) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && !el.disabled && !el.readOnly) {
      return el.id || el.name || 'email';
    }
  }
  return '';
})()
"""

FILL_ID_JS = r"""
(() => {
""" + _WALK_PREAMBLE + r"""
  const val = %VAL%;
  const sel = %SEL%;
  const el = document.querySelector(sel);
  if (!el) return '';
  return setNative(el, val) ? (el.id || el.placeholder || 'ok') : '';
})()
"""

REFRESH_CAPTCHA_JS = r"""
(() => {
  const el = document.querySelector('#captchaControlChallengeCode-generateCaptchaBtn, button[id*="generateCaptcha"]');
  if (!el) return '';
  el.click();
  return el.id || 'refresh';
})()
"""

PAGE_INFO_JS = r"""
(() => {
  const bodies = [];
  const grab = (doc) => {
    try { bodies.push((doc.body && doc.body.innerText || '').slice(0, 1200)); } catch (e) {}
  };
  grab(document);
  try {
    for (const f of [...(window.frames || [])]) {
      try { grab(f.document); } catch (e) {}
    }
  } catch (e) {}
  return JSON.stringify({
    url: location.href,
    title: document.title,
    body: bodies.join('\n---\n').slice(0, 2200),
  });
})()
"""

SESSION_JS = r"""
(() => {
  const cookies = document.cookie || '';
  const map = {};
  for (const part of cookies.split(';')) {
    const [k, ...rest] = part.split('=');
    const key = (k || '').trim();
    if (key) map[key] = rest.join('=').trim();
  }
  let ls = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) ls[k] = String(localStorage.getItem(k) || '').slice(0, 80);
    }
  } catch (e) {}
  return JSON.stringify({
    url: location.href,
    cookie_keys: Object.keys(map),
    session_id: map.session_id || map.sessionId || '',
    localStorage_keys: Object.keys(ls),
  });
})()
"""

USER_FETCH_JS = r"""
(async () => {
  try {
    const r = await fetch('/api/user', { credentials: 'include' });
    const t = await r.text();
    return JSON.stringify({ status: r.status, body: t.slice(0, 1500) });
  } catch (e) {
    return JSON.stringify({ error: String(e) });
  }
})()
"""

IS_LOGIN_JS = r"""
(async () => {
  try {
    const r = await fetch('/api/is_login', { credentials: 'include' });
    const t = await r.text();
    return JSON.stringify({ status: r.status, body: t.slice(0, 80) });
  } catch (e) {
    return JSON.stringify({ error: String(e) });
  }
})()
"""

STRIPE_JS = r"""
(() => {
  const href = location.href || '';
  if (href.includes('checkout.stripe.com')) return href;
  const html = document.documentElement ? document.documentElement.innerHTML : '';
  const m = html.match(/cs_live_[a-zA-Z0-9]+/);
  if (m) return 'https://checkout.stripe.com/c/pay/' + m[0];
  return '';
})()
"""

HAS_CLAIM_JS = r"""
(() => {
""" + _WALK_PREAMBLE + r"""
  return walk((doc) => {
    const els = [...doc.querySelectorAll('button, a, [role=button], div, span')].filter(vis);
    const hit = els.find(el => /claim my free month|free month/i.test(labelOf(el)));
    return hit ? labelOf(hit).slice(0, 60) : '';
  }) || '';
})()
"""

HAS_EMAIL_JS = r"""
(() => {
""" + _WALK_PREAMBLE + r"""
  return walk((doc) => {
    const inputs = [...doc.querySelectorAll('input')].filter(vis);
    const el = inputs.find(i => /email/i.test(
      (i.placeholder||'') + (i.name||'') + (i.id||'') + (i.type||'') +
      (i.getAttribute('aria-label')||'')
    ));
    return el ? (el.placeholder || el.name || el.id || 'email') : '';
  }) || '';
})()
"""


def _json_lit(val: Any) -> str:
    return json.dumps(val, ensure_ascii=False)


async def _js(tab: Any, script: str) -> Any:
    for name in ("execute_script", "evaluate"):
        fn = getattr(tab, name, None)
        if not fn:
            continue
        try:
            raw = await fn(script)
        except TypeError:
            try:
                raw = await fn(script, return_by_value=True)
            except Exception:
                continue
        except Exception:
            continue
        if isinstance(raw, dict):
            inner = raw
            for _ in range(5):
                if not isinstance(inner, dict):
                    break
                if "value" in inner and "type" in inner:
                    return inner.get("value")
                if "result" in inner:
                    inner = inner["result"]
                    continue
                break
            return inner
        return raw
    return None


async def _sleep(sec: float) -> None:
    raise_if_stop()
    await asyncio.sleep(sec)


def _port_busy(port: int) -> bool:
    try:
        import requests

        r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=0.4)
        return r.status_code < 500
    except Exception:
        return False


def kill_tool_chrome() -> int:
    ps = r"""
$ErrorActionPreference='SilentlyContinue'
$n = 0
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -match 'genspark\\chrome_runs' -or
    $_.CommandLine -match 'genspark/chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=99'
  )
} | ForEach-Object {
  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ } catch {}
}
Write-Output $n
"""
    hide = {}
    try:
        import sys as _sys
        from pathlib import Path as _Path

        _gr = _Path(__file__).resolve().parents[2] / "grok_tool"
        if _gr.is_dir() and str(_gr) not in _sys.path:
            _sys.path.insert(0, str(_gr))
        from grokreg.core import winhide

        hide = winhide.kwargs()
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=12,
            **hide,
        )
        n = int((r.stdout or "0").strip().splitlines()[-1] or 0)
        if n:
            log.info("Dọn Chrome Genspark cũ: killed≈%s", n)
        return n
    except Exception as e:
        log.debug("kill chrome: %s", e)
        return 0


def _chrome_options(config: dict[str, Any], port: int):
    from pydoll.browser.options import ChromiumOptions

    opt = ChromiumOptions()

    def add(arg: str) -> None:
        try:
            opt.add_argument(arg)
        except Exception:
            pass

    # Anti-flag chung từ grok_tool: fingerprint args (viewport random, lang,
    # webrtc, canvas) + browser prefs + fresh profile mỗi acc. Engine tự thêm
    # port/headless/window-position/proxy bên dưới.
    from gsparkreg.paths import ensure_grok_on_path

    ensure_grok_on_path()
    from grokreg.browser.anti_flag import harden_options

    config["_fingerprint"] = harden_options(config, opt, engine_root=ROOT)
    add(f"--remote-debugging-port={port}")
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        add(f"--proxy-server={proxy}")
    if config.get("headless"):
        add("--headless=new")
    mode = str(config.get("chrome_window_mode") or "offscreen").lower()
    if mode in ("offscreen", "minimized", "background", "hidden") and not config.get("headless"):
        add(f"--window-position={config.get('chrome_window_position') or '-2400,40'}")
    return opt


async def open_browser(config: dict[str, Any]):
    from pydoll.browser.chromium import Chrome

    kill_tool_chrome()
    await _sleep(0.6)
    port = int(config.get("chrome_debug_port") or 9944)
    if _port_busy(port):
        for cand in range(port, port + 40):
            if not _port_busy(cand):
                port = cand
                config["chrome_debug_port"] = port
                log.info("Port bận — dùng %s", port)
                break
    last_err: Exception | None = None
    for attempt in range(1, 4):
        opt = _chrome_options(config, port)
        log.info("Chrome start debug_port=%s (lan %s)", port, attempt)
        try:
            browser = Chrome(options=opt, connection_port=port)
            tab = await browser.start()
            try:
                from grokreg.browser.anti_flag import enable_stealth_auto

                await enable_stealth_auto(tab, config.get("_fingerprint") or {})
            except Exception as e:
                log.debug("stealth auto: %s", e)
            return browser, tab
        except Exception as e:
            last_err = e
            log.warning("Chrome start fail lan %s: %s", attempt, e)
            kill_tool_chrome()
            await _sleep(1.0)
            port += 1
            config["chrome_debug_port"] = port
    raise last_err or RuntimeError("Failed to start the browser")


async def close_browser(browser: Any) -> None:
    if browser:
        for name in ("stop", "close"):
            fn = getattr(browser, name, None)
            if fn:
                try:
                    await fn()
                except Exception:
                    pass
                break
    kill_tool_chrome()


async def _page(tab: Any) -> dict[str, Any]:
    raw = await _js(tab, PAGE_INFO_JS)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {"body": raw, "url": ""}
    return raw if isinstance(raw, dict) else {}


def _dump_page(info: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_page.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2)[:8000],
        encoding="utf-8",
    )


def _blocked_mail(info: dict[str, Any]) -> bool:
    blob = f"{info.get('body','')}".lower()
    return any(
        w in blob
        for w in (
            "disposable",
            "temporary email",
            "not allowed",
            "can't use this email",
            "invalid email",
            "try a different email",
            "email already exists",
            "already registered",
        )
    )


def _captcha_wrong(info: dict[str, Any]) -> bool:
    blob = f"{info.get('body','')}".lower()
    return any(
        w in blob
        for w in (
            "characters you entered didn't match",
            "captcha is incorrect",
            "incorrect captcha",
            "invalid captcha",
            "didn't match",
        )
    )


async def _click_texts(tab: Any, wants: list[str], tags: str = "button, a, [role=button]") -> str:
    script = CLICK_TEXT_JS.replace("%WANTS%", _json_lit(wants)).replace("%TAGS%", _json_lit(tags))
    raw = await _js(tab, script)
    return str(raw or "")


async def _click_id(tab: Any, selector: str) -> str:
    raw = await _js(tab, CLICK_ID_JS.replace("%SEL%", _json_lit(selector)))
    return str(raw or "")


async def _fill_id(tab: Any, selector: str, value: str) -> str:
    script = FILL_ID_JS.replace("%SEL%", _json_lit(selector)).replace("%VAL%", _json_lit(value))
    raw = await _js(tab, script)
    return str(raw or "")


async def _fill(tab: Any, value: str, hints: list[str]) -> str:
    script = (
        FILL_BY_PLACEHOLDER_JS.replace("%VAL%", _json_lit(value)).replace("%HINTS%", _json_lit(hints))
    )
    raw = await _js(tab, script)
    return str(raw or "")


async def _open_signup(tab: Any) -> None:
    """B2C CombinedSigninAndSignup — skip homepage (Cloudflare)."""
    log.info("Mở %s", LOGIN_API)
    await tab.go_to(LOGIN_API)
    await _sleep(3.5)
    info = await _page(tab)
    log.info("B2C login url=%s body=%s", str(info.get("url") or "")[:90], str(info.get("body") or "")[:120])
    clicked = await _click_id(tab, "#createAccount")
    if not clicked:
        clicked = await _click_texts(tab, ["sign up now"], "a, button, [role=button]")
    log.info("Click Sign up now: %s", clicked or "(none)")
    await _sleep(3.0)
    # Login page also has #email — chỉ tính xong khi (URL local=signup hoặc có
    # ảnh captcha) VÀ ô email thật sự render trong DOM (B2C đổi URL trước khi
    # JS render form — căn URL không thì fill luôn hit trang "Loading...").
    for _ in range(15):
        cap = str(await _js(tab, EXTRACT_CAPTCHA_JS) or "")
        url = str((await _page(tab)).get("url") or "").lower()
        has_email = str(await _js(tab, EMAIL_FIELD_JS) or "")
        if ("local=signup" in url or cap.startswith("data:image")) and has_email:
            log.info(
                "Signup form ready url=%s captcha=%s email_field=%s",
                url[:90], bool(cap), has_email,
            )
            return
        if not clicked:
            clicked = await _click_id(tab, "#createAccount")
            if clicked:
                log.info("Click Sign up now (retry): %s", clicked)
        await _sleep(0.8)
    log.warning("Chưa vào form signup — url=%s", str((await _page(tab)).get("url") or "")[:90])


async def _solve_captcha_candidates(tab: Any, config: dict[str, Any]) -> list[str]:
    """Lấy ảnh captcha + list đáp án để thử lần lượt trên CÙNG ảnh."""
    src = ""
    for _ in range(15):
        src = str(await _js(tab, EXTRACT_CAPTCHA_JS) or "")
        if src.startswith("data:image") and len(src) > 80:
            break
        await _sleep(0.4)
    if not src.startswith("data:image"):
        return []
    log.info("CAPTCHA image len=%s", len(src))
    try:
        cands = await asyncio.to_thread(solve_image_candidates, src, config)
    except Exception as e:
        log.warning("CAPTCHA solve fail: %s", e)
        raise
    return [c for c in cands if c][:3]


async def _fill_captcha_answer(tab: Any, ans: str) -> str:
    filled = await _fill_id(tab, "#captchaControlChallengeCode", ans)
    if not filled:
        filled = await _fill(
            tab,
            ans,
            ["enter the characters you see", "captcha", "captchaControlChallengeCode"],
        )
    log.info("Fill CAPTCHA field=%s ans=%s", filled or "(miss)", ans)
    return filled


async def _send_verification(tab: Any) -> str:
    clicked = await _click_id(tab, "#emailVerificationControl_but_send_code")
    if clicked:
        return clicked
    return await _click_texts(
        tab,
        ["send verification code", "send code"],
        "button, [type=submit], [role=button]",
    )


async def _wait_logged_in(tab: Any, *, rounds: int = 12) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for _ in range(rounds):
        info = await _page(tab)
        last = info
        url = str(info.get("url") or "")
        if "genspark.ai" in url and "login" not in url.lower() and "b2c" not in url.lower():
            chk = await _js(tab, IS_LOGIN_JS)
            log.info("is_login %s url=%s", str(chk)[:80], url[:80])
            return info
        await _sleep(1.5)
    return last


async def _dump_session(tab: Any, email: str) -> dict[str, Any]:
    sess_raw = await _js(tab, SESSION_JS)
    session: dict[str, Any] = {}
    if isinstance(sess_raw, str):
        try:
            session = json.loads(sess_raw)
        except Exception:
            session = {"raw": sess_raw}
    elif isinstance(sess_raw, dict):
        session = sess_raw
    session["email"] = email
    user_raw = await _js(tab, USER_FETCH_JS)
    if isinstance(user_raw, str):
        try:
            session["user_api"] = json.loads(user_raw)
        except Exception:
            session["user_api"] = user_raw[:400]
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2)[:12000],
        encoding="utf-8",
    )
    return session


async def _claim_month(tab: Any) -> str:
    log.info("Mở pricing %s", PRICING)
    await tab.go_to(PRICING)
    await _sleep(3.5)
    label = ""
    for _ in range(10):
        label = str(await _js(tab, HAS_CLAIM_JS) or "")
        if label:
            break
        await _sleep(1.5)
    if not label:
        log.info("Không thấy Claim My Free Month")
        return ""
    clicked = await _click_texts(
        tab,
        ["claim my free month", "free month"],
        "button, a, [role=button]",
    )
    log.info("Claim click: %s", clicked or label)
    stripe = ""
    for _ in range(12):
        await _sleep(1.2)
        stripe = str(await _js(tab, STRIPE_JS) or "")
        if stripe:
            log.info("Stripe %s", stripe[:90])
            return stripe
    return stripe


async def _signup_on_tab(
    tab: Any,
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    await _open_signup(tab)

    # B2C render chậm: retry fill ~12s thay vì bỏ cuộc ngay khi DOM chưa xong.
    filled = ""
    for _ in range(12):
        filled = await _fill_id(tab, "#email", email)
        if not filled:
            filled = await _fill_id(tab, 'input[type="email"]', email)
        if not filled:
            filled = await _fill(tab, email, ["email address", "email"])
        if filled:
            break
        await _sleep(1.0)
    log.info("Fill email=%s", filled or "(miss)")
    if not filled:
        info = await _page(tab)
        _dump_page(info)
        return {"ok": False, "status": "error:email_field_missing", "detail": str(info.get("url") or "")[:180]}

    captcha_ok = False
    last_cap_err = ""
    info: dict[str, Any] = {}
    for attempt in range(8):
        try:
            cands = await _solve_captcha_candidates(tab, config)
            if not cands:
                last_cap_err = "no captcha image"
                await _sleep(1.2)
                continue
        except Exception as e:
            last_cap_err = str(e)[:180]
            if "Thiếu captcha" in last_cap_err or "2captcha_key" in last_cap_err:
                return {"ok": False, "status": "error:need_captcha", "detail": last_cap_err}
            await _sleep(1.0)
            continue
        # Thử từng đáp án OCR trên CÙNG ảnh trước khi refresh — B2C cho đoán
        # lại nhiều lần, mỗi ảnh thêm ~2 lần cơ hội trúng.
        for ans in cands:
            await _fill_captcha_answer(tab, ans)
            sent = await _send_verification(tab)
            log.info("Send verification: %s (try %s ans=%s)", sent or "(none)", attempt + 1, ans)
            otp_ready = ""
            for _ in range(8):
                await _sleep(0.8)
                info = await _page(tab)
                otp_ready = str(
                    await _js(
                        tab,
                        "(() => { const el=document.querySelector('#emailVerificationCode'); return (el && !el.disabled) ? 'ready' : ''; })()",
                    )
                    or ""
                )
                if otp_ready or _captcha_wrong(info) or _blocked_mail(info):
                    break
            if _blocked_mail(info):
                _dump_page(info)
                return {"ok": False, "status": "error:email_blocked", "detail": str(info.get("body") or "")[:180]}
            if otp_ready:
                captcha_ok = True
                break
            log.info("CAPTCHA sai (ans=%s) — thử đáp án khác trên cùng ảnh (%s)", ans, str(info.get("body") or "")[:60])
        if captcha_ok:
            break
        log.warning("Hết đáp án cho ảnh này — refresh captcha")
        await _js(tab, REFRESH_CAPTCHA_JS)
        await _sleep(1.2)
    if not captcha_ok:
        info = await _page(tab)
        _dump_page(info)
        return {
            "ok": False,
            "status": "error:captcha_failed",
            "detail": last_cap_err or str(info.get("body") or "")[:180],
        }

    sent_at = time.time()
    mail = wait_mail(timeout=int(config.get("timeout_otp") or 180), after_ts=sent_at)
    code = str((mail or {}).get("code") or "").strip()
    if not code:
        return {"ok": False, "status": "error:no_otp", "detail": "hết timeout không thấy mã Genspark"}

    filled_code = await _fill_id(tab, "#emailVerificationCode", code)
    if not filled_code:
        filled_code = await _fill(
            tab,
            code,
            ["verification code", "verif", "otp", "emailVerificationCode"],
        )
    log.info("Fill OTP field=%s code=%s", filled_code or "(miss)", code)
    if not filled_code:
        info = await _page(tab)
        _dump_page(info)
        return {"ok": False, "status": "error:otp_field_missing", "detail": str(info.get("body") or "")[:180]}
    verify_btn = await _click_id(tab, "#emailVerificationControl_but_verify_code")
    if not verify_btn:
        verify_btn = await _click_texts(tab, ["verify code"], "button, [type=submit], [role=button]")
    log.info("Verify code click: %s", verify_btn or "(none)")
    await _sleep(3.0)

    n_pwd = 0
    for _ in range(16):
        a = await _fill_id(tab, "#newPassword", password)
        b = await _fill_id(tab, "#reenterPassword", password)
        n_pwd = int(bool(a)) + int(bool(b))
        if n_pwd >= 2:
            break
        n_pwd = int(await _js(tab, FILL_PASSWORDS_JS.replace("%VAL%", _json_lit(password))) or 0)
        if n_pwd:
            break
        await _sleep(0.6)
    log.info("Fill password fields=%s", n_pwd)
    if not n_pwd:
        info = await _page(tab)
        _dump_page(info)
        return {"ok": False, "status": "error:password_field_missing", "detail": str(info.get("body") or "")[:180]}
    await _sleep(0.8)
    cont = await _click_id(tab, "#continue")
    if not cont:
        cont = str(await _js(tab, CLICK_CONTINUE_JS) or "")
    log.info("Create/Continue: %s", cont)
    await _sleep(6.0)

    info = await _wait_logged_in(tab, rounds=14)
    url_now = str(info.get("url") or "")
    if "login.genspark" in url_now.lower() or "b2clogin" in url_now.lower() or "b2c_1" in url_now.lower():
        log.info("Vẫn trên B2C (%s) — mở homepage", url_now[:80])
        await tab.go_to(HOME)
        await _sleep(3.5)
        info = await _wait_logged_in(tab, rounds=10)
    _dump_page(info)
    session = await _dump_session(tab, email)
    url = str(session.get("url") or info.get("url") or "")
    user_api = session.get("user_api") if isinstance(session.get("user_api"), dict) else {}
    logged = bool(
        session.get("session_id")
        or (isinstance(user_api, dict) and user_api.get("status") == 200)
        or (APP_RE.search(url) and "login" not in url.lower() and "b2c" not in url.lower())
    )
    if not logged and "genspark.ai" in url and "login" not in url.lower() and "b2clogin" not in url.lower():
        logged = True
    if not logged:
        return {
            "ok": False,
            "status": "error:not_in_app",
            "detail": url[:180],
            "session": session,
        }

    extra = url[:160]
    stripe = ""
    if claim_free_month(config):
        try:
            stripe = await _claim_month(tab)
        except Exception as e:
            log.warning("claim month: %s", e)
        if stripe:
            session["stripe_url"] = stripe
            extra = stripe[:180]
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / "last_session.json").write_text(
                json.dumps(session, ensure_ascii=False, indent=2)[:12000],
                encoding="utf-8",
            )
            return {"ok": True, "status": "success:claimed", "session": session, "detail": extra}
        return {"ok": True, "status": "success:no_offer", "session": session, "detail": extra}
    return {"ok": True, "status": "success", "session": session, "detail": extra}


class CdpTab:
    """Attach to an already-running Chrome (GPM remote debug)."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._id = 0

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        msg_id = self._id
        await self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            raw = json.loads(await self._ws.recv())
            if raw.get("id") == msg_id:
                if raw.get("error"):
                    raise RuntimeError(str(raw["error"])[:200])
                return raw.get("result") or {}

    async def go_to(self, url: str) -> None:
        await self._call("Page.enable")
        await self._call("Runtime.enable")
        await self._call("Page.navigate", {"url": url})
        for _ in range(40):
            await asyncio.sleep(0.25)
            href = await self.execute_script("location.href")
            if href and str(href).startswith("http"):
                break

    async def execute_script(self, script: str) -> Any:
        expr = script if str(script).strip().startswith("(") else f"(() => {{ {script} }})()"
        result = await self._call(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        inner = result.get("result") if isinstance(result, dict) else {}
        if isinstance(inner, dict):
            return inner.get("value")
        return inner


async def open_gpm_tab(debug_address: str):
    import websockets

    host = debug_address.strip()
    if host.startswith("http"):
        host = host.split("://", 1)[-1]
    import requests as _rq

    base = f"http://{host}"

    def _pages() -> list[dict[str, Any]]:
        tabs = _rq.get(f"{base}/json", timeout=8).json()
        if not isinstance(tabs, list):
            return []
        return [t for t in tabs if isinstance(t, dict) and t.get("type") == "page"]

    async def _create_page_ws() -> str:
        ver = _rq.get(f"{base}/json/version", timeout=8).json()
        bws_url = str(ver.get("webSocketDebuggerUrl") or "")
        if not bws_url:
            return ""
        bws = await websockets.connect(bws_url, max_size=1_000_000)
        try:
            await bws.send(json.dumps({
                "id": 1, "method": "Target.createTarget",
                "params": {"url": "about:blank"},
            }))
            while True:
                raw = json.loads(await bws.recv())
                if raw.get("id") == 1:
                    return str((raw.get("result") or {}).get("targetId") or "")
        finally:
            await bws.close()

    page = next(iter(_pages()), {})
    if not page:
        target_id = await _create_page_ws()
        pages = _pages()
        page = next(
            (t for t in pages if str(t.get("id") or "") == target_id),
            pages[0] if pages else {},
        )
    ws_url = str(page.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise RuntimeError(f"GPM không có CDP websocket cấp page tại {host}")
    log.info("GPM attach %s", ws_url[:80])
    ws = await websockets.connect(ws_url, max_size=8_000_000)
    return CdpTab(ws), ws


async def register_browser(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    browser = None
    try:
        browser, tab = await open_browser(config)
        return await _signup_on_tab(tab, config, email=email, password=password, wait_mail=wait_mail)
    except Exception as e:
        log.exception("browser: %s", e)
        return {"ok": False, "status": f"error:{str(e)[:80]}", "detail": str(e)[:200]}
    finally:
        await close_browser(browser)


async def register_gpm(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    from gsparkreg.gpm import start_profile, stop_profile

    started: dict[str, Any] | None = None
    ws = None
    try:
        started = start_profile(config)
        tab, ws = await open_gpm_tab(str(started.get("debug_address") or ""))
        return await _signup_on_tab(tab, config, email=email, password=password, wait_mail=wait_mail)
    except Exception as e:
        log.exception("gpm: %s", e)
        return {"ok": False, "status": f"error:{str(e)[:80]}", "detail": str(e)[:200]}
    finally:
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if started and config.get("gpm_stop_after", True):
            stop_profile(config, str(started.get("profile_id") or ""))
