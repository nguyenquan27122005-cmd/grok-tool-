"""Chrome signup for Manus (pydoll) — email OTP / magic link on manus.im/login."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from manreg.log import log
from manreg.paths import DATA, ROOT
from manreg.stop import raise_if_stop

LOGIN_URL = "https://manus.im/login"
APP_URL = "https://manus.im/app"
INVITE_URL = "https://manus.im/invitation/"
# OpenCLI #1836: Next.js SPA, cookie-mode login, public /invitation/<id> /app
APP_RE = re.compile(r"manus\.im/(app|home|workspace|chat|dashboard|projects)(/|$)", re.I)

FILL_EMAIL_JS = r"""
(() => {
  const email = %EMAIL%;
  const reactProps = (el) => {
    try {
      const k = Object.keys(el).find(k => k.startsWith('__reactProps$'));
      return k ? (el[k] || {}) : {};
    } catch (e) { return {}; }
  };
  const sev = (el, val, key) => ({ target: el, currentTarget: el, value: val, key: key,
    preventDefault() {}, stopPropagation() {}, persist() {} });
  // Gõ TỪNG KÝ TỰ qua onKeyDown/onChange trong reactProps: manus.im tích luỹ
  // email vào store nội bộ qua keydown từng phím — chỉ bơm value + input event
  // thì submit vẫn gửi {} "email is empty" (gặp thật trên GPM lẫn Chrome thường,
  // browser anti-detect còn phá _valueTracker nữa).
  const typeInto = (el, val) => {
    if (!el) return false;
    el.focus();
    try { el.click(); } catch (e) {}
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    const p = reactProps(el);
    let cur = '';
    for (const ch of String(val)) {
      cur += ch;
      try { if (typeof p.onKeyDown === 'function') p.onKeyDown(sev(el, cur, ch)); } catch (e) {}
      const prev = el.value;
      if (desc && desc.set) desc.set.call(el, cur);
      else el.value = cur;
      if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
      el.dispatchEvent(new Event('input', { bubbles: true }));
      try { if (typeof p.onChange === 'function') p.onChange(sev(el, cur)); } catch (e) {}
    }
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 8 && r.height > 8;
  };
  const inputs = [...document.querySelectorAll('input')].filter(vis);
  const emailEl = inputs.find(i =>
    /email|user/i.test((i.type||'') + (i.name||'') + (i.id||'') + (i.placeholder||'') + (i.autocomplete||''))
  ) || inputs.find(i => i.type === 'email' || i.type === 'text');
  return typeInto(emailEl, email) ? 1 : 0;
})()
"""

FILL_PASSWORD_JS = r"""
(() => {
  const password = %PASSWORD%;
  const setNative = (el, val) => {
    if (!el) return false;
    el.focus();
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    let p = {};
    try {
      const k = Object.keys(el).find(k => k.startsWith('__reactProps$'));
      p = k ? (el[k] || {}) : {};
    } catch (e) {}
    const sev = (v, key) => ({ target: el, currentTarget: el, value: v, key: key,
      preventDefault() {}, stopPropagation() {}, persist() {} });
    // Gõ từng ký tự như FILL_EMAIL_JS — store nội bộ của trang ăn theo keydown.
    let cur = '';
    for (const ch of String(val)) {
      cur += ch;
      try { if (typeof p.onKeyDown === 'function') p.onKeyDown(sev(cur, ch)); } catch (e) {}
      const prev = el.value;
      if (desc && desc.set) desc.set.call(el, cur);
      else el.value = cur;
      if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
      el.dispatchEvent(new Event('input', { bubbles: true }));
      try { if (typeof p.onChange === 'function') p.onChange(sev(cur)); } catch (e) {}
    }
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 8 && r.height > 8;
  };
  const passEl = [...document.querySelectorAll('input')].filter(vis).find(i =>
    i.type === 'password' || /pass/i.test((i.name||'') + (i.id||'') + (i.placeholder||''))
  );
  return setNative(passEl, password) ? 1 : 0;
})()
"""

CLICK_EMAIL_JS = r"""
(() => {
  const texts = [
    'continue with email', 'sign up with email', 'use email',
    'sign in with email', 'email address',
  ];
  const deny = /google|apple|facebook|microsoft|github|passkey/;
  const nodes = [...document.querySelectorAll('button, a, [role=button]')];
  for (const want of texts) {
    for (const el of nodes) {
      const t = (el.innerText || el.textContent || '').trim().toLowerCase();
      if (!t || t.length > 48 || deny.test(t)) continue;
      if (t === want || t.includes(want)) { el.click(); return t.slice(0, 40); }
    }
  }
  return '';
})()
"""

SUBMIT_JS = r"""
(() => {
  // GPM profile locale vi-VN → manus.im render tiếng Việt; nhận cả hai.
  const prefer = [
    'send code', 'gửi mã', 'send link', 'gửi liên kết',
    'continue', 'tiếp tục', 'sign in', 'đăng nhập',
    'sign up', 'đăng ký', 'verify', 'xác minh', 'xác nhận',
    'next', 'tiếp theo', 'get started', 'bắt đầu',
    'create account', 'tạo tài khoản',
  ];
  const deny =
    /google|apple|sso|facebook|github|microsoft|passkey|kh[oó]a truy c[aậ]p/;
  const btns = [...document.querySelectorAll('button, [type=submit], [role=button], a')];
  const label = (el) => (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
  for (const want of prefer) {
    const hit = btns.find(el => {
      const t = label(el);
      return t && t.length < 60 && t.includes(want) && !deny.test(t);
    });
    if (hit) {
      // Nút có thể đang disabled đợi Turnstile callback — bật cưỡng bức.
      if (hit.disabled) { hit.disabled = false; hit.removeAttribute('disabled'); }
      hit.click();
      return (hit.disabled ? 'OFF!' : '') + label(hit).slice(0, 50);
    }
  }
  const submit = document.querySelector('button[type=submit], input[type=submit]');
  if (submit) {
    if (submit.disabled) { submit.disabled = false; submit.removeAttribute('disabled'); }
    submit.click(); return 'submit';
  }
  return '';
})()
"""

FILL_CODE_JS = r"""
(() => {
  const code = %CODE%;
  const vis = (el) => {
    if (!el || (el.type || '').toLowerCase() === 'password') return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 4 && r.height > 4;
  };
  const inputs = [...document.querySelectorAll('input')].filter(vis);
  const proto = window.HTMLInputElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
  const put = (el, val) => {
    el.focus();
    let p = {};
    try {
      const k = Object.keys(el).find(k => k.startsWith('__reactProps$'));
      p = k ? (el[k] || {}) : {};
    } catch (e) {}
    const sev = (v, key) => ({ target: el, currentTarget: el, value: v, key: key,
      preventDefault() {}, stopPropagation() {}, persist() {} });
    try { if (typeof p.onKeyDown === 'function') p.onKeyDown(sev(val, String(val)[0])); } catch (e) {}
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, val);
    else el.value = val;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    el.dispatchEvent(new Event('input', { bubbles: true }));
    try { if (typeof p.onChange === 'function') p.onChange(sev(val)); } catch (e) {}
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  // Layout nhiều ô — mỗi ô 1 chữ số (maxlength=1): rải code vào từng ô,
  // chỉ set 1 ký tự thì ô mới nhận đủ, không bị cắt còn số đầu tiên.
  const boxes = inputs.filter(i =>
    i.maxLength === 1 && !/email|user|pass/i.test((i.name||'') + (i.id||''))
  );
  if (boxes.length >= code.length) {
    boxes.slice(0, code.length).forEach((el, idx) => put(el, code[idx]));
    return boxes.length;
  }
  // Ô đơn nhận cả mã
  const el = inputs.find(i =>
    /otp|code|verif|pin/i.test((i.name||'') + (i.id||'') + (i.placeholder||'') + (i.autocomplete||'') + (i.inputMode||''))
  ) || inputs.find(i => (i.maxLength === -1 || i.maxLength > code.length) && (i.inputMode === 'numeric' || /otp|code/i.test(i.name+i.id+i.placeholder+i.autocomplete)));
  if (!el) return 0;
  put(el, code);
  return 1;
})()
"""

ONBOARD_JS = r"""
(() => {
  const txt = (el) => (el.innerText || el.textContent || '').trim();
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 8 && r.height > 8;
  };
  const deny = /google|apple|facebook|privacy|terms|upgrade|subscribe|pricing/;
  const nextRe = /continue|next|skip|done|finish|get started|confirm|let'?s go|tiếp|bỏ qua|hoàn tất/;
  const btns = [...document.querySelectorAll('button, [role=button], a')].filter(vis);
  const nxt = btns.find(el => {
    const t = txt(el);
    return t && t.length < 28 && nextRe.test(t) && !deny.test(t);
  });
  if (nxt) { nxt.click(); return 'next:' + txt(nxt).slice(0, 20); }
  return '';
})()
"""

SESSION_JS = r"""
(() => {
  const cookies = document.cookie || '';
  let session_id = '';
  for (const part of cookies.split(';')) {
    const [k, ...rest] = part.split('=');
    if ((k || '').trim() === 'session_id') session_id = rest.join('=').trim();
  }
  const ls = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const v = localStorage.getItem(k) || '';
      if (/token|auth|session|user/i.test(k) && v.length < 4000) ls[k] = v;
    }
  } catch (e) {}
  return JSON.stringify({
    url: location.href,
    cookie_len: cookies.length,
    session_id: session_id,
    ls_keys: Object.keys(ls),
  });
})()
"""

PAGE_INFO_JS = r"""
(() => {
  return JSON.stringify({
    url: location.href,
    title: document.title,
    body: (document.body && document.body.innerText || '').slice(0, 1400),
  });
})()
"""


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



_INVISIBLE_RE = re.compile(r"<script[\s\S]*?</script>|<noscript[\s\S]*?</noscript>|<style[\s\S]*?</style>", re.I)


def _visible_html(html: str) -> str:
    """HTML bỏ phần <script>/<style>/<noscript> — captcha chỉ tính khi HIỆN trên trang."""
    return _INVISIBLE_RE.sub(" ", html or "")


def _captcha_hit(html: str) -> str:
    m = re.search(
        r"captcha|turnstile|hcaptcha|recaptcha|unusual traffic|please finish the verification",
        _visible_html(html),
        re.I,
    )
    return m.group(0) if m else ""


async def _try_captcha(tab: Any, config: dict[str, Any], *, url: str, reason: str) -> bool:
    """Gặp Turnstile → gọi solver local (:5072) lấy token rồi bơm vào trang."""
    try:
        from manreg.captcha import solve_and_inject

        return await solve_and_inject(tab, config, _js, page_url=url, reason=reason)
    except Exception as exc:  # noqa: BLE001 — captcha fail không được giết job
        log.warning("[captcha] luồng giải lỗi: %s", exc)
        return False


TURNSTILE_PRESENT_JS = (
    "!!document.querySelector("
    "'.cf-turnstile, [class*=\"turnstile\"], "
    'iframe[src*="challenges.cloudflare"], \'[data-sitekey]\')'
)


def _port_busy(port: int) -> bool:
    try:
        import requests

        r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=0.4)
        return r.status_code < 500
    except Exception:
        return False


def requests_get_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """GET JSON cho loopback — tắt trust_env để không đi theo HTTP_PROXY hệ thống."""
    import requests

    s = requests.Session()
    s.trust_env = False
    return s.get(url, timeout=timeout).json()


def kill_tool_chrome() -> int:
    ps = r"""
$ErrorActionPreference='SilentlyContinue'
$n = 0
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -match 'manus\\chrome_runs' -or
    $_.CommandLine -match 'manus/chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=96'
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
            log.info("Dọn Chrome Manus cũ: killed≈%s", n)
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
    from manreg.paths import ensure_grok_on_path

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


async def open_browser(config: dict[str, Any], *, use_gpm: bool = False):
    """use_gpm=True: không tự chạy Chrome — start profile GPM rồi nối pydoll
    vào CDP do GPM mở (fingerprint anti-detect, tránh Turnstile chặn)."""
    if use_gpm:
        from pydoll.browser.chromium import Chrome

        from manreg.gpm import ensure_profile, start_profile

        pid = ensure_profile(config, str(config.get("gpm_profile_name") or "manus"))
        config["_gpm_profile_id"] = pid
        info = start_profile({**config, "gpm_profile": pid})
        addr = str(info.get("debug_address") or "")
        ver = requests_get_json(f"http://{addr}/json/version")
        ws = str(ver.get("webSocketDebuggerUrl") or "")
        if not ws:
            raise RuntimeError(f"GPM CDP {addr} không trả webSocketDebuggerUrl: {ver}")
        browser = Chrome(connection_port=int(addr.rpartition(":")[2]))
        tab = await browser.connect(ws)
        log.info("GPM connected CDP=%s (profile %s)", addr, pid)
        return browser, tab

    from pydoll.browser.chromium import Chrome

    kill_tool_chrome()
    await _sleep(0.6)
    port = int(config.get("chrome_debug_port") or 9644)
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


async def close_browser(
    browser: Any,
    *,
    use_gpm: bool = False,
    profile_id: str = "",
    config: dict[str, Any] | None = None,
) -> None:
    if browser:
        # GPM quản chromium của chính nó — chỉ ngắt websocket (close), tuyệt
        # đối không stop() giết process hay kill_tool_chrome theo port 96xx.
        for name in (("close",) if use_gpm else ("stop", "close")):
            fn = getattr(browser, name, None)
            if fn:
                try:
                    await fn()
                except Exception:
                    pass
                break
    if use_gpm and config is not None and profile_id:
        try:
            from manreg.gpm import stop_profile

            stop_profile(config, profile_id)
        except Exception as e:
            log.debug("gpm stop skip: %s", e)
        return
    kill_tool_chrome()


async def dump_network(tab: Any, tag: str) -> None:
    try:
        url = await _js(tab, "location.href")
        html = await _js(tab, "document.body ? document.body.innerText.slice(0, 4000) : ''")
        path = DATA / f"network_capture_{int(time.time())}.json"
        path.write_text(
            json.dumps({"tag": tag, "url": url, "html": html}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("capture %s → %s", tag, path.name)
    except Exception as e:
        log.debug("capture: %s", e)


def _parse_info(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        try:
            j = json.loads(raw)
            if isinstance(j, dict):
                return {str(k): str(v) for k, v in j.items()}
        except Exception:
            return {"body": raw}
    return {"body": str(raw or "")}


def _logged_in(url: str, html: str) -> bool:
    blob = f"{url} {html}"
    if APP_RE.search(blob):
        return True
    if re.search(r"sign in or sign up|continue with google|continue with email", html, re.I):
        return False
    return False


def _session_email(token: str) -> str:
    """Đọc email trong JWT session của Manus (payload segment, b64url).
    Trả '' nếu không decode được — lúc đó KHÔNG kết luận acc nào."""
    import base64

    parts = str(token or "").split(".")
    if len(parts) < 2:
        return ""
    seg = parts[1]
    seg += "=" * (-len(seg) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(seg))
    except Exception:  # noqa: BLE001 — token lạ
        return ""
    return str(payload.get("email") or "").strip().lower()


def _session_ok(sess: dict[str, Any], email: str) -> bool:
    """Session này có thật sự của acc đang reg không?

    Profile GPM dùng lại nhiều lần nên localStorage còn sót session của acc
    cũ — từng gặp thật: tool báo success cho acc mới nhưng JWT lại là email
    lần chạy trước. Chỉ nhận khi email trong JWT khớp (hoặc đọc không ra)."""
    sid = str(sess.get("session_id") or "")
    if not sid:
        return False
    owner = _session_email(sid)
    if not owner or not email:
        return True  # không xác định được chủ — giữ hành vi cũ
    return owner == str(email).strip().lower()


async def register_browser(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail,
    use_gpm: bool = False,
) -> dict[str, Any]:
    signup = str(config.get("signup_url") or LOGIN_URL)
    browser = None
    try:
        browser, tab = await open_browser(config, use_gpm=use_gpm)
        invite = str(config.get("invite_code") or "").strip()
        start = f"{INVITE_URL}{invite}" if invite else signup
        log.info("Mở %s", start)
        await tab.go_to(start)
        # KHÔNG dọn storage/reload ở đây: xoá cookie làm rớt challenge của
        # Cloudflare và load lại khiến nút submit im lặng (đã A/B thấy thật).
        # Session acc cũ sót lại đã có _session_ok() kiểm tra email trong JWT.
        await _sleep(3.5)
        if invite and "invitation" in start:
            await _sleep(1.5)
            cur = str(await _js(tab, "location.href") or "")
            if "login" not in cur.lower() and "/app" not in cur.lower():
                await tab.go_to(signup)
                await _sleep(2.5)
        info = _parse_info(await _js(tab, PAGE_INFO_JS))
        log.info("UI: %s %s", info.get("url"), (info.get("body") or "")[:220])

        clicked = await _js(tab, CLICK_EMAIL_JS)
        if clicked:
            log.info("Click: %s", clicked)
            await _sleep(1.8)

        filled_e = await _js(tab, FILL_EMAIL_JS.replace("%EMAIL%", json.dumps(email)))
        log.info("Fill email=%s", filled_e)
        filled_p = await _js(tab, FILL_PASSWORD_JS.replace("%PASSWORD%", json.dumps(password)))
        if filled_p:
            log.info("Fill password=%s", filled_p)

        # KHÔNG giải Turnstile chủ động ở màn login nữa: widget ở đây là chế độ
        # ẩn tự pass; tiêm token ngoài làm nút Continue kẹt OFF rồi submit im
        # lặng (gặp thật trên profile GPM). Chỉ can thiệp khi bail-out phát hiện.
        submitted = await _js(tab, SUBMIT_JS)
        log.info("Submit: %s", submitted)
        await _sleep(4.0)

        # Turnstile invisible chấm điểm TỪNG lần: pass thì request auth đi
        # kèm email đầy đủ, rượt thì trang im re (đã bắt mạng thấy thật).
        # Kiên trì: điền lại email + giải token ngoài (phòng hờ) + bấm lại,
        # lần pass tự nhiên thường tới sau vài chục giây.
        for _login_try in range(4):
            _u = str(await _js(tab, "location.href") or "")
            _t = str(await _js(
                tab, "document.body ? document.body.innerText.slice(0, 500) : ''") or "")
            if APP_RE.search(_u) or not re.search(r"continue|tiếp tục", _t, re.I):
                break
            log.info("Chưa qua màn login (lan %s) — điền lại + giải Turnstile + submit",
                     _login_try + 1)
            await _js(tab, FILL_EMAIL_JS.replace("%EMAIL%", json.dumps(email)))
            await _try_captcha(tab, config, url=LOGIN_URL,
                               reason=f"login lan {_login_try + 1}")
            await _js(tab, SUBMIT_JS)
            await _sleep(4.0)

        await dump_network(tab, "after_submit")

        url = str(await _js(tab, "location.href") or "")
        html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or "")
        log.info("UI after submit: %s | %s", url.split("?")[0], html[:220].replace("\n", " / "))
        if re.search(
            r"flagged|spam|blocked|not allowed|invalid email"
            r"|email không h[aạ]p l[eệ]",
            html,
            re.I,
        ):
            return {"ok": False, "status": "error:email_flagged", "url": url, "detail": html[:200]}
        _hit = _captcha_hit(html)
        if _hit:
            log.info("Phát hiện captcha (%s) — thử giải tự động", _hit)
            if not await _try_captcha(tab, config, url=url, reason="sau submit"):
                return {"ok": False, "status": "error:need_captcha", "url": url, "detail": f"match={_hit}: {html[:180]}"}
            await _sleep(2.0)
            url = str(await _js(tab, "location.href") or url)
            html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or html)
            log.info("UI sau captcha: %s | %s", url.split("?")[0], html[:220].replace("\n", " / "))
            if _captcha_hit(html) or re.search(
                r"continue with google|continue with facebook|continue with apple", html, re.I
            ):
                await _js(tab, SUBMIT_JS)
                log.info("Submit lại sau khi có token")
                await _sleep(5.0)
                url = str(await _js(tab, "location.href") or url)
                html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or html)
                log.info("UI sau submit lại: %s | %s", url.split("?")[0], html[:220].replace("\n", " / "))
                if _captcha_hit(html):
                    return {"ok": False, "status": "error:need_captcha", "url": url,
                            "detail": f"solver xong nhưng vẫn captcha: {html[:180]}"}

        invite = str(config.get("invite_code") or "").strip()
        if invite and re.search(r"invite|invitation", html + url, re.I):
            n = await _js(tab, FILL_CODE_JS.replace("%CODE%", json.dumps(invite)))
            log.info("Fill invite=%s", n)
            await _js(tab, SUBMIT_JS)
            await _sleep(2.0)
            html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or html)

        sess0 = _parse_info(await _js(tab, SESSION_JS))
        if _logged_in(url, html) or _session_ok(sess0, email):
            token = str(sess0.get("session_id") or "")
            credits: dict[str, Any] = {}
            if token:
                try:
                    from manreg.credits import fetch_credits

                    credits = fetch_credits(config, token)
                except Exception as e:
                    log.warning("credits skip: %s", e)
            return {
                "ok": True,
                "status": "success",
                "url": url,
                "session": {"email": email, "url": url, "session_id": token, **sess0, "credits": credits},
            }

        still_oauth = bool(re.search(r"continue with google|continue with facebook|continue with apple", html, re.I))
        need_verify = bool(re.search(
            r"check your email|enter the code|verification code|magic link|we sent (a |you )?(code|link)",
            html,
            re.I,
        ))
        proof: dict[str, str] = {}
        if still_oauth and not re.search(r"set your password|create your account", html, re.I):
            log.info("SPA còn OAuth — thử click email lần 2")
            clicked2 = await _js(tab, CLICK_EMAIL_JS)
            if clicked2:
                log.info("Retry click: %s", clicked2)
                await _sleep(1.5)
            filled2 = await _js(tab, FILL_EMAIL_JS.replace("%EMAIL%", json.dumps(email)))
            log.info("Retry fill email=%s", filled2)
            submitted2 = await _js(tab, SUBMIT_JS)
            log.info("Retry submit: %s", submitted2)
            await _sleep(4.0)
            url = str(await _js(tab, "location.href") or url)
            html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or html)
            log.info("UI after retry: %s | %s", url.split("?")[0], html[:220].replace("\n", " / "))
            still_oauth = bool(re.search(r"continue with google|continue with facebook|continue with apple", html, re.I))
            need_verify = bool(re.search(
                r"check your email|enter the code|verification code|magic link|we sent (a |you )?(code|link)",
                html,
                re.I,
            ))
            _hit = _captcha_hit(html)
            if _hit:
                log.info("Vẫn captcha sau lần thử lại (%s) — giải rồi submit tiếp", _hit)
                if not await _try_captcha(tab, config, url=url, reason="thử OAuth lần 2"):
                    return {"ok": False, "status": "error:need_captcha", "url": url, "detail": f"match={_hit}: {html[:180]}"}
                await _js(tab, SUBMIT_JS)
                await _sleep(5.0)
                url = str(await _js(tab, "location.href") or url)
                html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or html)
                log.info("UI sau captcha lần 2: %s | %s", url.split("?")[0], html[:220].replace("\n", " / "))
                still_oauth = bool(re.search(r"continue with google|continue with facebook|continue with apple", html, re.I))
                need_verify = bool(re.search(
                    r"check your email|enter the code|verification code|magic link|we sent (a |you )?(code|link)",
                    html,
                    re.I,
                ))
                _hit = _captcha_hit(html)
                if _hit:
                    return {"ok": False, "status": "error:need_captcha", "url": url,
                            "detail": f"solver xong nhưng vẫn captcha: {html[:180]}"}
            if still_oauth and not need_verify and not re.search(r"set your password|create your account", html, re.I):
                return {
                    "ok": False,
                    "status": "error:submit_no_verify_ui",
                    "url": url,
                    "detail": "Vẫn màn OAuth — email chưa gửi (SPA). " + html[:160],
                }
        if re.search(r"set your password|create your account|create a password", html, re.I):
            n_p = await _js(tab, FILL_PASSWORD_JS.replace("%PASSWORD%", json.dumps(password)))
            log.info("Fill password (create account)=%s", n_p)
            await _js(tab, SUBMIT_JS)
            await _sleep(3.5)
            url = str(await _js(tab, "location.href") or url)
            html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or html)
            log.info("UI after password: %s | %s", url.split("?")[0], html[:200].replace("\n", " / "))
            sess0 = _parse_info(await _js(tab, SESSION_JS))
            if _logged_in(url, html) or _session_ok(sess0, email):
                token = str(sess0.get("session_id") or "")
                credits: dict[str, Any] = {}
                if token:
                    try:
                        from manreg.credits import fetch_credits

                        credits = fetch_credits(config, token)
                        log.info("[credits] %s", credits.get("summary") or credits.get("status"))
                    except Exception as e:
                        log.warning("credits skip: %s", e)
                return {
                    "ok": True,
                    "status": "success",
                    "url": url,
                    "session": {"email": email, "url": url, "session_id": token, **sess0, "credits": credits},
                }
            need_verify = bool(re.search(r"verif|inbox|confirm|check your email|sent|magic|enter the code", html + url, re.I))
        if still_oauth and not need_verify:
            return {
                "ok": False,
                "status": "error:submit_no_verify_ui",
                "url": url,
                "detail": "Vẫn màn OAuth — email chưa gửi (SPA/captcha). " + html[:160],
            }
        if need_verify:
            log.info("Chờ mail Manus…")
            proof = wait_mail() or {}
            if proof.get("link"):
                log.info("Mở magic link %s", proof["link"][:90])
                await tab.go_to(proof["link"])
                await _sleep(5)
            elif proof.get("code"):
                n = await _js(tab, FILL_CODE_JS.replace("%CODE%", json.dumps(proof["code"])))
                log.info("Fill OTP=%s", n)
                await _sleep(0.8)
                await _js(tab, SUBMIT_JS)
                # Đợi trang thật sự thoát màn verify (redirect/onboard mất vài
                # giây); Turnstile tái xuất hiện thì giải tiếp rồi submit lại.
                for _ in range(8):
                    await _sleep(2.0)
                    url = str(await _js(tab, "location.href") or url)
                    html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 1600) : ''") or html)
                    if APP_RE.search(url) or _logged_in(url, html):
                        break
                    if re.search(
                        r"invalid|incorrect|expired|wrong code"
                        r"|không (đúng|hợp lệ)|hết hạn|sai mã",
                        html,
                        re.I,
                    ):
                        log.warning("OTP bị từ chối: %s", html[:140])
                        break
                    if _captcha_hit(html):
                        if await _try_captcha(tab, config, url=url, reason="sau OTP"):
                            await _js(tab, SUBMIT_JS)
            else:
                return {"ok": False, "status": "error:otp_timeout", "url": url}

        for _ in range(4):
            acted = await _js(tab, ONBOARD_JS)
            if acted:
                log.info("Onboard: %s", acted)
                await _sleep(1.2)
            else:
                break

        url = str(await _js(tab, "location.href") or "")
        html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 1600) : ''") or "")
        sess = _parse_info(await _js(tab, SESSION_JS))
        await dump_network(tab, "final")
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "last_session.json").write_text(
            json.dumps({"email": email, "url": url, "session": sess}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        token = str(sess.get("session_id") or "")
        logged = _logged_in(url, html) or (bool(token) and APP_RE.search(url or ""))
        # Session sót từ acc cũ trong profile dùng lại thì KHÔNG tính —
        # chỉ nhận khi JWT khớp email đang reg (đã gặp thật, báo success oan).
        owner = _session_email(token)
        if logged and token and owner and owner != str(email).strip().lower():
            log.warning("Session trên trang thuộc acc khác (%s) — bỏ qua.", owner)
            logged = False
        if logged:
            credits: dict[str, Any] = {}
            if token:
                try:
                    from manreg.credits import fetch_credits

                    credits = fetch_credits(config, token)
                    log.info("[credits] %s", credits.get("summary") or credits.get("status"))
                except Exception as e:
                    log.warning("credits skip: %s", e)
            return {
                "ok": True,
                "status": "success",
                "url": url,
                "session": {
                    "email": email,
                    "url": url,
                    "session_id": token,
                    **sess,
                    "credits": credits,
                },
            }
        if not filled_e:
            return {"ok": False, "status": "error:no_signup_fields", "url": url}
        # Manus từ 08/2026 bắt xác minh SĐT sau OTP email — tool chưa có
        # nguồn số điện thoại. Thử nước cờ: tài khoản có thể đã tạo xong sau
        # OTP email → vào thẳng /app; vào được là khỏi cần SIM.
        if re.search(r"verify[-_ ]?phone|verify your phone", f"{url} {html}", re.I):
            log.info("Màn xác minh SĐT — thử bỏ qua: vào thẳng %s …", APP_URL)
            try:
                await tab.go_to(APP_URL)
                for _ in range(5):
                    await _sleep(2.0)
                    url = str(await _js(tab, "location.href") or url)
                    html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 1600) : ''") or html)
                    sess = _parse_info(await _js(tab, SESSION_JS))
                    if (_logged_in(url, html) or _session_ok(sess, email)) and _session_ok(sess, email):
                        break
            except Exception as e:
                log.debug("skip phone err: %s", e)
            token = str(sess.get("session_id") or "")
            owner = _session_email(token)
            if owner and owner != str(email).strip().lower():
                log.warning("Session trên trang là của acc cũ (%s) — không tính.", owner)
                token = ""
            if token and (APP_RE.search(url or "") or _session_ok(sess, email)):
                log.info("Bỏ qua SĐT THÀNH CÔNG — acc dùng được luôn")
                credits: dict[str, Any] = {}
                try:
                    from manreg.credits import fetch_credits

                    credits = fetch_credits(config, token)
                    log.info("[credits] %s", credits.get("summary") or credits.get("status"))
                except Exception as e:
                    log.warning("credits skip: %s", e)
                return {
                    "ok": True,
                    "status": "success",
                    "url": url,
                    "session": {
                        "email": email,
                        "url": url,
                        "session_id": token,
                        **sess,
                        "credits": credits,
                        "phone_skipped": "1",
                    },
                }
            return {
                "ok": False,
                "status": "error:need_phone_verify",
                "url": url,
                "detail": "Manus yêu cầu xác minh số điện thoại (SMS) sau khi "
                          "xác minh email — cần nguồn số SIM/API SMS để làm tiếp. "
                          + html[:160],
                "session": {"email": email, "url": url},
            }
        return {
            "ok": False,
            "status": "error:signup_incomplete",
            "url": url,
            "detail": html[:240],
            "session": {"email": email, "url": url},
        }
    finally:
        await close_browser(browser, use_gpm=use_gpm,
                            profile_id=str(config.get("_gpm_profile_id") or ""),
                            config=config if use_gpm else None)
