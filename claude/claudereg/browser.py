"""Chrome signup for Claude.ai (pydoll) — email + 6-digit code."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from claudereg.config import random_name
from claudereg.log import log
from claudereg.paths import DATA, ROOT
from claudereg.stop import raise_if_stop

LOGIN_URL = "https://claude.ai/login"
APP_RE = re.compile(
    r"claude\.ai/(?:new|chat|recents|projects|settings|onboarding)|console\.anthropic\.com",
    re.I,
)

FILL_EMAIL_JS = r"""
(() => {
  const email = %EMAIL%;
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 8 && r.height > 8;
  };
  const setNative = (el, val) => {
    if (!el) return false;
    el.focus();
    try { el.click(); } catch (e) {}
    const proto = window.HTMLInputElement.prototype;
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
  const inputs = [...document.querySelectorAll('input')].filter(vis);
  const emailEl = inputs.find(i =>
    /email/i.test((i.type||'') + (i.name||'') + (i.id||'') + (i.placeholder||'') + (i.autocomplete||''))
  ) || inputs.find(i => i.type === 'email' || i.type === 'text');
  return setNative(emailEl, email) ? 1 : 0;
})()
"""

CLICK_EMAIL_METHOD_JS = r"""
(() => {
  const btns = [...document.querySelectorAll('button, [role=button], a')];
  const label = (el) => (el.innerText || el.textContent || '').trim().toLowerCase();
  const hit = btns.find(el => {
    const t = label(el);
    return t === 'continue with email' || t.includes('continue with email');
  });
  if (hit) { hit.click(); return label(hit).slice(0, 40); }
  return '';
})()
"""

SUBMIT_JS = r"""
(() => {
  const deny = /google|apple|github|sso|passkey|microsoft|continue with email/;
  const btns = [...document.querySelectorAll('button, [type=submit], [role=button], a')];
  const label = (el) => (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
  const submit = [...document.querySelectorAll('button[type=submit], input[type=submit]')].find(el => {
    const t = label(el);
    return t && !deny.test(t);
  });
  if (submit) { submit.click(); return 'type-submit:' + label(submit).slice(0, 40); }
  const prefer = ['send code', 'send login code', 'continue', 'next', 'sign up'];
  for (const want of prefer) {
    const hit = btns.find(el => {
      const t = label(el);
      return t && t.length < 40 && t.includes(want) && !deny.test(t);
    });
    if (hit) { hit.click(); return label(hit).slice(0, 50); }
  }
  return '';
})()
"""

FILL_CODE_JS = r"""
(() => {
  const code = String(%CODE% || '');
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 4 && r.height > 4;
  };
  const setNative = (el, val) => {
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
    try { el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: val.slice(-1) })); } catch (e) {}
  };
  const all = [...document.querySelectorAll('input, textarea, [contenteditable=true]')].filter(vis);
  const inputs = all.filter(i => !i.type || !/email|password|hidden|checkbox|radio|submit/.test(i.type));
  const boxes = inputs.filter(i => i.tagName === 'INPUT' && (i.maxLength === 1 || i.size === 1 || (String(i.inputMode||'') === 'numeric' && (i.maxLength || 1) <= 2)));
  if (boxes.length >= 4 && code.length >= 4) {
    boxes.slice(0, code.length).forEach((el, i) => setNative(el, code[i] || ''));
    return boxes.length;
  }
  const el = inputs.find(i =>
    /otp|code|verif|pin|one-time|one_time/i.test(
      (i.name||'') + (i.id||'') + (i.placeholder||'') + (i.autocomplete||'') + (i.getAttribute('aria-label')||'')
    )
  ) || inputs.find(i => (i.maxLength && i.maxLength >= 4 && i.maxLength <= 8) || i.inputMode === 'numeric' || i.pattern)
    || inputs.find(i => i.type === 'tel' || i.type === 'number' || i.type === 'text');
  if (!el) return 0;
  setNative(el, code);
  return 1;
})()
"""

FILL_NAME_JS = r"""
(() => {
  const first = %FIRST%;
  const last = %LAST%;
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 8 && r.height > 8;
  };
  const setNative = (el, val) => {
    if (!el) return false;
    el.focus();
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, val);
    else el.value = val;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };
  const inputs = [...document.querySelectorAll('input')].filter(vis)
    .filter(i => i.type !== 'email' && i.type !== 'password' && i.type !== 'hidden' && i.type !== 'tel');
  let n = 0;
  const firstEl = inputs.find(i => /first|given/i.test((i.name||'')+(i.id||'')+(i.placeholder||'')+(i.autocomplete||'')));
  const lastEl = inputs.find(i => /last|family|surname/i.test((i.name||'')+(i.id||'')+(i.placeholder||'')+(i.autocomplete||'')));
  const nameEl = inputs.find(i => /full.?name|^name$/i.test((i.name||'')+(i.id||'')+(i.placeholder||'')+(i.autocomplete||'')));
  if (firstEl) { setNative(firstEl, first); n++; }
  if (lastEl) { setNative(lastEl, last); n++; }
  if (!n && nameEl) { setNative(nameEl, first + ' ' + last); n++; }
  return n;
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
  let did = '';
  const boxes = [...document.querySelectorAll('input[type=checkbox], [role=checkbox]')].filter(vis);
  for (const b of boxes) {
    const on = b.checked || b.getAttribute('aria-checked') === 'true';
    if (!on) {
      try { b.click(); did += 'check '; } catch (e) {}
    }
  }
  const deny = /google|apple|github|privacy policy|opens in a new|upgrade|subscribe|pricing|billing|card|terms of/;
  const nextRe = /continue|next|done|finish|get started|skip|personal|for myself|agree|create account|accept/;
  const btns = [...document.querySelectorAll('button, [role=button], a')].filter(vis);
  const nxt = btns.find(el => {
    const t = txt(el).toLowerCase();
    return t && t.length < 40 && nextRe.test(t) && !deny.test(t);
  });
  if (nxt) { nxt.click(); return (did + 'next:' + txt(nxt).slice(0, 24)).trim(); }
  return did.trim();
})()
"""

PAGE_INFO_JS = r"""
(() => {
  return JSON.stringify({
    url: location.href,
    title: document.title,
    body: (document.body && document.body.innerText || '').slice(0, 1800),
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
  return JSON.stringify({
    url: location.href,
    cookie_keys: Object.keys(map),
    sessionKey: map.sessionKey || map.session_key || '',
    lastActiveOrg: map.lastActiveOrg || '',
  });
})()
"""


def _json_lit(val: str) -> str:
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
    $_.CommandLine -match 'claude\\chrome_runs' -or
    $_.CommandLine -match 'claude/chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=98'
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
            log.info("Dọn Chrome Claude cũ: killed≈%s", n)
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
    from claudereg.paths import ensure_grok_on_path

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
    port = int(config.get("chrome_debug_port") or 9844)
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


def _phone_wall(info: dict[str, Any]) -> bool:
    blob = f"{info.get('url','')} {info.get('title','')} {info.get('body','')}".lower()
    return any(
        w in blob
        for w in (
            "verify your phone",
            "phone number",
            "sms code",
            "enter your phone",
            "số điện thoại",
        )
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
        )
    )


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
    info = None
    import requests as _rq

    base = f"http://{host}"

    # Phải nối vào endpoint cấp PAGE (/json list). /json/version trả websocket
    # cấp BROWSER — Page./Runtime. không tồn tại ở đó nên mọi lệnh sau đó văng
    # "'Page.enable' wasn't found" (đã gặp thật khi chạy backend gpm).
    def _pages() -> list[dict[str, Any]]:
        tabs = _rq.get(f"{base}/json", timeout=8).json()
        if not isinstance(tabs, list):
            return []
        return [t for t in tabs if isinstance(t, dict) and t.get("type") == "page"]

    async def _create_page_ws() -> str:
        """Chưa có tab nào → tạo qua Target.createTarget trên browser ws."""
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
        # Chưa có tab nào → tạo qua Target.createTarget trên browser ws rồi
        # lấy lại websocket cấp page của tab vừa tạo.
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


async def _signup_on_tab(
    tab: Any,
    config: dict[str, Any],
    *,
    email: str,
    wait_mail: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    log.info("Mở %s", LOGIN_URL)
    await tab.go_to(LOGIN_URL)

    # React mount chậm: poll chờ nút "Continue with email" thật sự bấm được
    # thay vì ngủ cố định rồi bấm vào khoảng trống (trang còn loading).
    method = ""
    for _ in range(15):
        method = await _js(tab, CLICK_EMAIL_METHOD_JS)
        if method:
            break
        await _sleep(1.0)
    log.info("Click email method: %s", method)
    await _sleep(1.0)

    # Form email chỉ xuất hiện SAU khi bấm method — poll cho tới khi fill ăn.
    filled = 0
    for _ in range(12):
        filled = await _js(tab, FILL_EMAIL_JS.replace("%EMAIL%", _json_lit(email)))
        if filled:
            break
        # method có thể chưa nhận lần đầu — bấm lại trong lúc poll
        if not method:
            method = await _js(tab, CLICK_EMAIL_METHOD_JS)
            if method:
                log.info("Click email method (retry): %s", method)
        await _sleep(1.0)
    log.info("Fill email=%s", filled)
    await _sleep(0.6)

    # SUBMIT_JS deny cả "continue with email" — nhưng trên claude.ai nút đó
    # vừa là method vừa là submit của form. Fallback: bấm method lần nữa.
    async def _submit_email_form() -> str:
        hit = await _js(tab, SUBMIT_JS)
        if not hit:
            hit = await _js(tab, CLICK_EMAIL_METHOD_JS)
        return str(hit or "")

    clicked = await _submit_email_form()
    log.info("Submit: %s", clicked)

    # Verify submit: trang phải rời lỗi "Email address is required" — nếu vẫn
    # lỗi thì fill lại + submit lại thay vì đi chờ OTP không bao giờ tới.
    for _ in range(6):
        await _sleep(1.5)
        info = await _page(tab)
        blob = str(info.get("body") or "")
        if "email address is required" not in blob.lower() and (
            str(info.get("url") or "") != LOGIN_URL or "verification" in blob.lower()
            or "check your email" in blob.lower() or "enter the code" in blob.lower()
        ):
            break
        log.info("Submit chưa ăn — fill lại + submit")
        await _js(tab, FILL_EMAIL_JS.replace("%EMAIL%", _json_lit(email)))
        await _sleep(0.6)
        await _submit_email_form()
    await _sleep(2.0)
    sent_at = time.time()

    info = await _page(tab)
    (DATA / "last_page.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2)[:8000],
        encoding="utf-8",
    )
    log.info("After email submit url=%s body=%s", str(info.get("url") or "")[:80], str(info.get("body") or "")[:160])
    if _blocked_mail(info):
        return {"ok": False, "status": "error:email_blocked", "detail": str(info.get("body") or "")[:180]}
    if _phone_wall(info):
        return {"ok": False, "status": "error:need_phone", "detail": "phone wall trước OTP"}

    mail = wait_mail(timeout=int(config.get("timeout_otp") or 180), after_ts=sent_at)
    code = str((mail or {}).get("code") or "").strip()
    link = str((mail or {}).get("link") or "").strip()
    if link:
        log.info("Mở magic link mail %s", link[:90])
        await tab.go_to(link)
        await _sleep(4.0)
    elif code:
        await _js(
            tab,
            "(() => { const n=[...document.querySelectorAll('button,a,[role=button]')].find(e=>/enter verification code|verification code/i.test((e.innerText||''))); if(n){n.click(); return 1;} return 0; })()",
        )
        await _sleep(0.8)
        n = 0
        for attempt in range(8):
            n = await _js(tab, FILL_CODE_JS.replace("%CODE%", _json_lit(code)))
            log.info("Fill OTP try=%s boxes=%s code=%s", attempt + 1, n, code)
            if n:
                break
            await _sleep(1.0)
        if not n:
            info = await _page(tab)
            (DATA / "last_page.json").write_text(
                json.dumps(info, ensure_ascii=False, indent=2)[:8000],
                encoding="utf-8",
            )
            return {
                "ok": False,
                "status": "error:otp_field_missing",
                "detail": str(info.get("body") or info.get("url") or "")[:220],
            }
        await _js(tab, SUBMIT_JS)
        await _sleep(3.0)
    else:
        return {"ok": False, "status": "error:no_otp", "detail": "hết timeout không thấy mã Claude"}

    first, last = random_name()
    named = await _js(
        tab,
        FILL_NAME_JS.replace("%FIRST%", _json_lit(first)).replace("%LAST%", _json_lit(last)),
    )
    if named:
        log.info("Fill name %s %s", first, last)
        await _js(tab, SUBMIT_JS)
        await _sleep(1.5)

    for _ in range(14):
        info = await _page(tab)
        if _phone_wall(info):
            return {"ok": False, "status": "error:need_phone", "detail": "Anthropic đòi SĐT"}
        url = str(info.get("url") or "")
        if re.search(r"claude\.ai/(?:new|chat|recents|projects)(?:/|$|\?)", url, re.I):
            break
        clicked = await _js(tab, ONBOARD_JS)
        if clicked:
            log.info("Onboard: %s", clicked)
        await _sleep(1.2)

    info = await _page(tab)
    if _phone_wall(info):
        return {"ok": False, "status": "error:need_phone", "detail": "phone wall sau OTP"}

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
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    url = str(session.get("url") or info.get("url") or "")
    body_l = str(info.get("body") or "").lower()
    in_app = bool(re.search(r"claude\.ai/(?:new|chat|recents|projects)(?:/|$|\?)", url, re.I))
    onboard_done = "onboarding" in url.lower() and "i agree" not in body_l
    ok = in_app or onboard_done or bool(session.get("sessionKey"))
    status = "success" if ok else "error:not_in_app"
    log.info("Claude URL=%s ok=%s body=%s", url[:80], ok, str(info.get("body") or "")[:180])
    if not ok:
        (DATA / "last_page.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2)[:8000],
            encoding="utf-8",
        )
    return {"ok": ok, "status": status, "session": session, "detail": url[:180]}


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
        return await _signup_on_tab(tab, config, email=email, wait_mail=wait_mail)
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
    from claudereg.gpm import start_profile, stop_profile

    started: dict[str, Any] | None = None
    ws = None
    try:
        started = start_profile(config)
        tab, ws = await open_gpm_tab(str(started.get("debug_address") or ""))
        return await _signup_on_tab(tab, config, email=email, wait_mail=wait_mail)
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
