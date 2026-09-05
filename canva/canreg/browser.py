"""Chrome signup Canva (pydoll) — Continue with email → tên → OTP."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from canreg.log import log
from canreg.paths import DATA, ROOT
from canreg.stop import raise_if_stop

SIGNUP_URL = "https://www.canva.com/signup/"

# Chrome bỏ qua credential trong --proxy-server (ERR_INVALID_AUTH_CREDENTIALS
# nếu để nguyên) — tách user:pass ra và trả lời challenge 407 qua CDP Fetch.
_PROXY_AUTH_PATTERN = "__no_request_match_proxy_auth__"


def split_proxy_creds(proxy: str) -> tuple[str, str, str]:
    """'http://user:pass@host:port' → ('http://host:port', 'user', 'pass')."""
    p = str(proxy or "").strip()
    if "://" in p and "@" in p:
        scheme, _, rest = p.partition("://")
        cred, _, hostport = rest.rpartition("@")
        if cred and hostport:
            user, _, pwd = cred.partition(":")
            return f"{scheme}://{hostport}", user, pwd
    return p, "", ""


async def setup_proxy_auth(tab: Any, config: dict[str, Any]) -> None:
    """Proxy có user:pass → đăng ký handler CDP Fetch.authRequired trên tab.

    Dùng url_pattern không bao giờ khớp để request thường KHÔNG bị pause;
    AuthRequired vẫn bắn vì chỉ phụ thuộc handleAuthRequests.
    """
    _, user, pwd = split_proxy_creds(str(config.get("proxy") or ""))
    if not user:
        return
    try:
        from pydoll.commands.fetch_commands import FetchCommands
        from pydoll.protocol.fetch.events import FetchEvent
        from pydoll.protocol.fetch.types import AuthChallengeResponseType

        await tab._execute_command(
            FetchCommands.enable(handle_auth_requests=True, url_pattern=_PROXY_AUTH_PATTERN)
        )

        async def _on_auth(event: dict[str, Any]) -> None:
            try:
                params = event.get("params") or event
                rid = params.get("requestId")
                if rid:
                    await tab.continue_with_auth(
                        rid,
                        AuthChallengeResponseType.PROVIDE_CREDENTIALS,
                        proxy_username=user,
                        proxy_password=pwd,
                    )
            except Exception as e:  # noqa: BLE001 — auth fail không được giết flow
                log.debug("proxy auth continue fail: %s", e)

        await tab.on(FetchEvent.AUTH_REQUIRED.value, _on_auth)
        log.info("Proxy auth CDP sẵn sàng (user=%s)", user)
    except Exception as e:  # noqa: BLE001 — không có auth handler vẫn chạy thử
        log.warning("Không bật được proxy auth CDP: %s", e)


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


def kill_canva_chrome(port: int | None = None) -> int:
    """Giết Chrome do tool mở. Có port thì chỉ giết Chrome của port đó
    (chế độ song song — tránh luồng này giết Chrome của luồng khác)."""
    import subprocess

    if port:
        cond = f"$_.CommandLine -match 'remote-debugging-port={port}'"
    else:
        cond = (
            "$_.CommandLine -match 'canva\\\\chrome_runs' -or "
            "$_.CommandLine -match 'canva/chrome_runs' -or "
            "$_.CommandLine -match 'remote-debugging-port=9844'"
        )
    ps = r"""
$ErrorActionPreference='SilentlyContinue'
$n = 0
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
  $_.CommandLine -and (COND)
} | ForEach-Object {
  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ } catch {}
}
Write-Output $n
""".replace("COND", cond)
    try:
        hide: dict[str, Any] = {}
        try:
            from canreg.paths import ensure_grok_on_path
            from grokreg.core import winhide

            ensure_grok_on_path()
            hide = winhide.kwargs()
        except Exception:
            pass
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=12,
            **hide,
        )
        n = int((r.stdout or "0").strip().splitlines()[-1] or 0)
        if n:
            log.info("Dọn Chrome Canva cũ: killed≈%s", n)
        return n
    except Exception as e:
        log.debug("kill canva chrome: %s", e)
        return 0


def park_canva_chrome(config: dict[str, Any]) -> None:
    import subprocess

    pos = str(config.get("chrome_window_position") or "-2400,40")
    try:
        x, y = [int(p.strip()) for p in pos.split(",")[:2]]
    except Exception:
        x, y = -2400, 40
    ps = f"""
$ErrorActionPreference='SilentlyContinue'
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class CvWin {{
  [DllImport("user32.dll")] public static extern bool SetWindowPos(
    IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}}
"@
$flags = [uint32]0x0015
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {{
  $_.CommandLine -and (
    $_.CommandLine -match 'canva\\\\chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=9844'
  )
}} | ForEach-Object {{
  $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
  if ($p -and $p.MainWindowHandle -ne [IntPtr]::Zero) {{
    [CvWin]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, {x}, {y}, 0, 0, $flags) | Out-Null
    [CvWin]::ShowWindowAsync($p.MainWindowHandle, 7) | Out-Null
  }}
}}
"""
    try:
        hide: dict[str, Any] = {}
        try:
            from canreg.paths import ensure_grok_on_path
            from grokreg.core import winhide

            ensure_grok_on_path()
            hide = winhide.kwargs()
        except Exception:
            pass
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=8,
            **hide,
        )
    except Exception as e:
        log.debug("park chrome: %s", e)


def show_canva_chrome() -> None:
    import subprocess

    ps = r"""
$ErrorActionPreference='SilentlyContinue'
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class CvShow {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(
    IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
}
"@
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -match 'canva\\chrome_runs' -or
    $_.CommandLine -match 'canva/chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=9844'
  )
} | ForEach-Object {
  $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
  if ($p -and $p.MainWindowHandle -ne [IntPtr]::Zero) {
    [CvShow]::ShowWindowAsync($p.MainWindowHandle, 3) | Out-Null
    [CvShow]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, 60, 40, 1200, 860, [uint32]0x0040) | Out-Null
    [CvShow]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  }
}
"""
    try:
        hide: dict[str, Any] = {}
        try:
            from canreg.paths import ensure_grok_on_path
            from grokreg.core import winhide

            ensure_grok_on_path()
            hide = winhide.kwargs()
        except Exception:
            pass
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=8,
            **hide,
        )
    except Exception as e:
        log.debug("show chrome: %s", e)


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
    from canreg.paths import ensure_grok_on_path

    ensure_grok_on_path()
    from grokreg.browser.anti_flag import harden_options

    config["_fingerprint"] = harden_options(config, opt, engine_root=ROOT)
    add(f"--remote-debugging-port={port}")
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        bare, user, _ = split_proxy_creds(proxy)
        if user:
            log.warning(
                "Proxy có user:pass — Chrome chỉ nhận host:port, auth sẽ trả lời qua CDP (407)"
            )
        add(f"--proxy-server={bare}")
    if config.get("headless"):
        add("--headless=new")
    mode = str(config.get("chrome_window_mode") or "offscreen").lower()
    if mode in ("offscreen", "minimized", "background", "hidden") and not config.get("headless"):
        add(f"--window-position={config.get('chrome_window_position') or '-2400,40'}")
    elif mode in ("visible", "normal", "front", "on"):
        add(f"--window-position={config.get('chrome_window_position') or '80,60'}")
        add("--start-maximized")
    return opt


async def open_browser(config: dict[str, Any], *, wipe_old: bool = True):
    from pydoll.browser.chromium import Chrome

    parallel = bool(config.get("chrome_parallel"))
    port = int(config.get("chrome_debug_port") or 9844)
    if wipe_old:
        # Song song: chỉ dọn Chrome của port mình, đừng đụng luồng khác
        kill_canva_chrome(port if parallel else None)
        await _sleep(0.6)
    if not _port_busy(port):
        pass
    else:
        for cand in range(port, port + 40):
            if not _port_busy(cand):
                port = cand
                config["chrome_debug_port"] = port
                log.info("Port bận — dùng %s", port)
                break
    last_err: Exception | None = None
    for attempt in range(1, 4):
        opt = _chrome_options(config, port)
        mode = str(config.get("chrome_window_mode") or "offscreen").lower()
        log.info(
            "Chrome start debug_port=%s (%s, lần %s)",
            port,
            "màn hình chính" if mode in ("visible", "normal", "front", "on") else "off-screen",
            attempt,
        )
        try:
            browser = Chrome(options=opt, connection_port=port)
            tab = await browser.start()
            try:
                from grokreg.browser.anti_flag import enable_stealth_auto

                await enable_stealth_auto(tab, config.get("_fingerprint") or {})
            except Exception as e:
                log.debug("stealth auto: %s", e)
            await setup_proxy_auth(tab, config)
            if mode in ("offscreen", "minimized", "background", "hidden"):
                park_canva_chrome(config)
                await _sleep(0.15)
                park_canva_chrome(config)
            else:
                show_canva_chrome()
            return browser, tab
        except Exception as e:
            last_err = e
            log.warning("Chrome start fail lần %s: %s", attempt, e)
            kill_canva_chrome()
            await _sleep(1.0)
            port += 1
            config["chrome_debug_port"] = port
    raise last_err or RuntimeError("Failed to start the browser")


async def close_browser(browser: Any, *, wipe_old: bool = True, port: int | None = None) -> None:
    if browser:
        for name in ("stop", "close"):
            fn = getattr(browser, name, None)
            if fn:
                try:
                    await fn()
                except Exception:
                    pass
                break
    if wipe_old:
        kill_canva_chrome(port)


async def dump_network(tab: Any, tag: str) -> None:
    try:
        url = await _js(tab, "location.href")
        html = await _js(tab, "document.documentElement.outerHTML.slice(0, 8000)")
        path = DATA / f"network_capture_{int(time.time())}.json"
        path.write_text(
            json.dumps({"tag": tag, "url": url, "html": html}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("capture %s → %s", tag, path.name)
    except Exception as e:
        log.debug("capture: %s", e)


CLICK_JS = r"""
(() => {
  const wants = %WANTS%;
  const deny = /google|facebook|apple|sso|microsoft|github|phone|sms|another way|terms|privacy|log in$|^log in/;
  const nodes = [...document.querySelectorAll('button, a, [role=button], [type=submit]')];
  const label = (el) => (el.innerText || el.textContent || el.value || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 8 && r.height > 8;
  };
  const live = nodes.filter(vis);
  for (const want of wants) {
    const exact = live.find(el => {
      const t = label(el);
      return t === want && !deny.test(t);
    });
    if (exact) { exact.click(); return label(exact).slice(0, 50); }
  }
  for (const want of wants) {
    const hit = live.find(el => {
      const t = label(el);
      if (!t || t.length > 48 || deny.test(t)) return false;
      if (want === 'continue' && /^continue with /.test(t)) return false;
      return t === want || (want.length >= 8 && t.includes(want));
    });
    if (hit) { hit.click(); return label(hit).slice(0, 50); }
  }
  return '';
})()
"""

SET_VALUE_JS = r"""
(() => {
  const val = %VAL%;
  const kind = %KIND%;
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 6 && r.height > 6 && !el.disabled && el.type !== 'hidden';
  };
  const setNative = (el, v) => {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, v);
    else el.value = v;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    try {
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: v, inputType: 'insertText' }));
    } catch (e) {
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Enter' }));
    return true;
  };
  const scorePanel = (el) => {
    const t = (el.innerText || '').slice(0, 500).toLowerCase();
    let s = 0;
    if (/email \(personal or work\)|we.ll check if you have an account/.test(t)) s += 6;
    if (/create your account|you.re creating a canva account/.test(t)) s += 6;
    if (/enter the code|you.re almost signed up|code we sent/.test(t)) s += 6;
    return s;
  };
  let root = document;
  let best = 0;
  for (const el of document.querySelectorAll('form, [role=dialog], section, article, main, div')) {
    if (!vis(el)) continue;
    const sc = scorePanel(el);
    if (sc > best && (el.innerText || '').length < 1800) { best = sc; root = el; }
  }
  const inputs = [...root.querySelectorAll('input, textarea')].filter(vis);
  const blob = (i) => (i.type + i.name + i.id + i.placeholder + (i.autocomplete||'') + i.inputMode).toLowerCase();
  let el = null;
  if (kind === 'email') {
    el = inputs.find(i => i.type === 'email' || /email|username/.test(blob(i)))
      || inputs.find(i => i.type === 'text' || !i.type);
  } else if (kind === 'name') {
    el = inputs.find(i => /name|display|full/.test(blob(i)))
      || inputs.find(i => (i.type === 'text' || !i.type) && !/email|otp|code|pin|username/.test(blob(i)));
  } else if (kind === 'code') {
    const boxes = inputs.filter(i => i.maxLength === 1 || i.inputMode === 'numeric');
    if (boxes.length >= 4 && String(val).length >= 4) {
      [...String(val)].forEach((d, i) => setNative(boxes[i], d));
      return boxes.length;
    }
    el = inputs.find(i => /otp|code|verif|pin/.test(blob(i)))
      || inputs.find(i => (i.maxLength && i.maxLength <= 8) || i.inputMode === 'numeric');
  }
  return setNative(el, val) ? 1 : 0;
})()
"""

OTP_STATE_JS = r"""
(() => {
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 4 && r.height > 4 && !el.disabled;
  };
  const inputs = [...document.querySelectorAll('input')].filter(vis);
  const el = inputs.find(i => (i.autocomplete || '') === 'one-time-code')
    || inputs.find(i => i.inputMode === 'numeric' || (i.maxLength > 0 && i.maxLength <= 8))
    || inputs[0];
  const body = (document.body && document.body.innerText || '').toLowerCase();
  return JSON.stringify({
    val: el ? String(el.value || '') : '',
    ac: el ? (el.autocomplete || '') : '',
    max: el ? el.maxLength : 0,
    mode: el ? (el.inputMode || '') : '',
    n: inputs.length,
    empty_err: /please enter your verification code/.test(body),
    bad_err: /incorrect|invalid|wrong code|try again|didn.t match/.test(body),
    resend_ready: /resend/.test(body) && !/resend in \d/.test(body),
  });
})()
"""

FILL_OTP_JS = r"""
(() => {
  const code = String(%VAL% || '');
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 4 && r.height > 4 && !el.disabled;
  };
  const setNative = (el, v) => {
    if (!el) return false;
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    const prev = el.value;
    el.focus();
    try { el.click(); } catch (e) {}
    try { el.select(); } catch (e) {}
    if (desc && desc.set) desc.set.call(el, v);
    else el.value = v;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    try { el.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, data: v, inputType: 'insertText' })); } catch (e) {}
    try { el.dispatchEvent(new InputEvent('input', { bubbles: true, data: v, inputType: 'insertText' })); }
    catch (e) { el.dispatchEvent(new Event('input', { bubbles: true })); }
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };
  const inputs = [...document.querySelectorAll('input')].filter(vis);
  const boxes = inputs.filter(i => i.maxLength === 1);
  let method = '';
  let el = inputs.find(i => (i.autocomplete || '') === 'one-time-code')
    || inputs.find(i => /otp|code|verif|pin|one-time/i.test(
      i.name + i.id + i.placeholder + (i.autocomplete || '') + i.inputMode
    ))
    || inputs.find(i => i.inputMode === 'numeric' || (i.maxLength > 0 && i.maxLength <= 8))
    || inputs[0];
  if (boxes.length >= 4 && code.length >= 4) {
    boxes.slice(0, code.length).forEach((box, i) => setNative(box, code[i] || ''));
    method = 'boxes';
    const got = boxes.slice(0, code.length).map(b => b.value || '').join('');
    return JSON.stringify({ok: got === code ? 1 : 0, val: got, method, n: boxes.length});
  }
  if (!el) return JSON.stringify({ok: 0, val: '', method: 'none', n: inputs.length});
  el.scrollIntoView({block: 'center', inline: 'nearest'});
  el.focus();
  try { el.click(); } catch (e) {}
  try { el.select(); } catch (e) {}
  try {
    if (document.execCommand('selectAll') && document.execCommand('insertText', false, code) && el.value === code) {
      method = 'execCommand';
    }
  } catch (e) {}
  if (el.value !== code) {
    setNative(el, code);
    method = method ? method + '+setter' : 'setter';
  }
  return JSON.stringify({ok: el.value === code ? 1 : 0, val: String(el.value || ''), method, max: el.maxLength, ac: el.autocomplete || ''});
})()
"""

RESEND_JS = r"""
(() => {
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 4 && r.height > 4 && !el.disabled;
  };
  const label = (el) => (el.innerText || el.textContent || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const nodes = [...document.querySelectorAll('button, a, [role=button], span')].filter(vis);
  const ready = nodes.find(el => {
    const t = label(el);
    if (!t || t.length > 64) return false;
    if (/resend in \d/.test(t)) return false;
    return t === 'resend' || t === 'resend code' || t.endsWith(' resend') || /^resend/.test(t);
  });
  if (ready) { ready.click(); return 'click:' + label(ready).slice(0, 40); }
  return '';
})()
"""

PAGE_INFO_JS = r"""
(() => {
  const texts = [...document.querySelectorAll('button, a, [role=button], input')]
    .slice(0, 40)
    .map(el => (el.innerText || el.textContent || el.placeholder || el.type || '').trim().slice(0, 50))
    .filter(Boolean);
  return JSON.stringify({
    url: location.href,
    title: document.title,
    body: (document.body && document.body.innerText || '').slice(0, 1400),
    controls: texts,
  });
})()
"""


def re_search(pat: str, text: str) -> bool:
    import re

    return bool(re.search(pat, text or "", re.I))


async def _body(tab: Any) -> str:
    return str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2200) : ''") or "")


async def _wait_cf(tab: Any, seconds: int = 24) -> None:
    for _ in range(max(4, seconds)):
        title = str(await _js(tab, "document.title") or "")
        body = await _body(tab)
        if re_search(r"just a moment|attention required|checking your browser", title + " " + body):
            await _sleep(1.2)
            continue
        break


async def _click(tab: Any, *wants: str) -> str:
    script = CLICK_JS.replace("%WANTS%", json.dumps([w.lower() for w in wants]))
    return str(await _js(tab, script) or "")


SUBMIT_FORM_JS = r"""
(() => {
  const deny = /google|facebook|apple|chatgpt|another way|terms|privacy|^log in$|sign up with|continue with/;
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 20 && r.height > 20;
  };
  const label = (el) => (el.innerText || el.textContent || el.value || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const scorePanel = (el) => {
    const t = (el.innerText || '').slice(0, 500).toLowerCase();
    let s = 0;
    if (/email \(personal or work\)|we.ll check if you have an account/.test(t)) s += 6;
    if (/create your account|you.re creating a canva account/.test(t)) s += 6;
    if (/enter the code|you.re almost signed up|code we sent/.test(t)) s += 6;
    return s;
  };
  let root = null;
  let best = 0;
  for (const el of document.querySelectorAll('form, [role=dialog], section, article, main, div')) {
    if (!vis(el)) continue;
    const sc = scorePanel(el);
    if (sc > best && (el.innerText || '').length < 1800) { best = sc; root = el; }
  }
  root = root || document;
  const btns = [...root.querySelectorAll('button, [type=submit], [role=button]')].filter(vis);
  const exact = btns.find(el => label(el) === 'continue' && !deny.test(label(el)));
  const create = btns.find(el => /^(continue|create account|verify|confirm|next|finish)$/.test(label(el)));
  const typed = btns.find(el => (el.getAttribute('type') || '').toLowerCase() === 'submit' && !deny.test(label(el)));
  const hit = exact || create || typed;
  if (hit) { hit.click(); return 'btn:' + label(hit).slice(0, 40); }
  const form = root.tagName === 'FORM' ? root : root.querySelector('form');
  if (form && form.requestSubmit) {
    try { form.requestSubmit(); return 'form.requestSubmit'; } catch (e) {}
  }
  return '';
})()
"""


async def _submit_form(tab: Any) -> str:
    return str(await _js(tab, SUBMIT_FORM_JS) or "")


async def _wait_stage(tab: Any, *, not_in: tuple[str, ...] = ("email",), seconds: float = 12) -> str:
    last = "unknown"
    steps = max(4, int(seconds))
    for i in range(steps):
        body = await _body(tab)
        url = str(await _js(tab, "location.href") or "")
        last = _stage(url, body)
        if last not in not_in:
            return last
        if re_search(r"load(ing)?…|please wait", body):
            log.info("Canva đang load…")
        await _sleep(1.0)
    return last


async def _press_enter(tab: Any) -> None:
    await _js(
        tab,
        """
(() => {
  const el = document.activeElement || document.querySelector('input:focus, input[type=email], input');
  if (!el) return 0;
  const opts = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true };
  el.dispatchEvent(new KeyboardEvent('keydown', opts));
  el.dispatchEvent(new KeyboardEvent('keypress', opts));
  el.dispatchEvent(new KeyboardEvent('keyup', opts));
  const form = el.form || el.closest('form');
  if (form && form.requestSubmit) try { form.requestSubmit(); } catch (e) {}
  return 1;
})()
""",
    )


def _stage(url: str, body: str) -> str:
    low = f"{url} {body}".lower()
    if re_search(
        r"temporary or disposable|don't allow temporary|ineligible|"
        r"can.t sign you up for security|sign you up for security reasons|"
        r"try (to )?(continue|sign up) with a different email",
        low,
    ):
        return "flagged"
    if re_search(
        r"your canva code|your login code|enter the code|we (just )?sent|check your email|"
        r"verification code|code we sent|you.re almost signed up|enter \d{6} in the next",
        low,
    ):
        return "otp"
    if re_search(
        r"create your account|you.re creating a canva account|"
        r"what should we call|account name|display name|your name",
        low,
    ):
        return "name"
    if re_search(r"email \(personal or work\)|we.ll check if you have an account", low):
        return "email"
    if "continue with email" in low and "creating a canva" not in low and "enter the code" not in low:
        if re_search(r"log in or sign up in seconds", low):
            return "landing"
    if _logged_in(url, body):
        return "home"
    return "unknown"


FOCUS_KIND_JS = r"""
(() => {
  const kind = %KIND%;
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 6 && r.height > 6 && !el.disabled && el.type !== 'hidden';
  };
  const scorePanel = (el) => {
    const t = (el.innerText || '').slice(0, 500).toLowerCase();
    let s = 0;
    if (/email \(personal or work\)|we.ll check if you have an account/.test(t)) s += 6;
    if (/create your account|you.re creating a canva account/.test(t)) s += 6;
    if (/enter the code|you.re almost signed up|code we sent/.test(t)) s += 6;
    return s;
  };
  let panel = null;
  let best = 0;
  for (const el of document.querySelectorAll('form, [role=dialog], section, article, main, div')) {
    if (!vis(el)) continue;
    const sc = scorePanel(el);
    if (sc > best && (el.innerText || '').length < 1800) {
      best = sc;
      panel = el;
    }
  }
  const root = panel || document;
  const inputs = [...root.querySelectorAll('input, textarea')].filter(vis);
  const all = inputs.map(i => ({
    type: i.type, ph: i.placeholder || '', ac: i.autocomplete || '',
    mode: i.inputMode || '', max: i.maxLength, name: i.name || ''
  }));
  const blob = (i) => (i.type + ' ' + i.name + ' ' + i.id + ' ' + i.placeholder + ' ' + (i.autocomplete || '') + ' ' + i.inputMode).toLowerCase();
  let el = null;
  if (kind === 'email') {
    el = inputs.find(i => i.type === 'email' || /email|username/.test(blob(i)))
      || inputs.find(i => i.type === 'text' || !i.type);
  } else if (kind === 'name') {
    el = inputs.find(i => /name|display|full/.test(blob(i)))
      || inputs.find(i => (i.type === 'text' || !i.type) && !/email|otp|code|pin|username/.test(blob(i)));
  } else if (kind === 'code') {
    const boxes = inputs.filter(i => i.maxLength === 1 || i.inputMode === 'numeric');
    el = boxes[0] || inputs.find(i => /otp|code|pin|one-time/.test(blob(i))) || inputs[0];
  }
  if (!el) return JSON.stringify({ok:0, n: inputs.length, best, all});
  el.scrollIntoView({block: 'center', inline: 'nearest'});
  el.focus();
  try { el.click(); } catch (e) {}
  try { el.select(); } catch (e) {}
  return JSON.stringify({
    ok: 1, tag: el.tagName, type: el.type, ph: el.placeholder || '',
    ac: el.autocomplete || '', max: el.maxLength, best, all
  });
})()
"""


async def _focus_kind(tab: Any, kind: str) -> dict[str, Any]:
    raw = await _js(tab, FOCUS_KIND_JS.replace("%KIND%", json.dumps(kind)))
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {"ok": 0, "raw": str(raw)[:80]}


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            out = json.loads(raw)
            return out if isinstance(out, dict) else {"raw": raw[:120]}
        except Exception:
            return {"raw": raw[:120]}
    return {}


async def _otp_state(tab: Any) -> dict[str, Any]:
    return _as_dict(await _js(tab, OTP_STATE_JS))


async def _fill_otp(tab: Any, code: str) -> dict[str, Any]:
    """Ghi mã vào ô one-time-code rồi mới bấm Continue. CDP-only hay để trống."""
    code = str(code or "").strip()
    before = await _otp_state(tab)
    log.info("OTP field trước %s", before)
    raw = await _js(tab, FILL_OTP_JS.replace("%VAL%", json.dumps(code)))
    filled = _as_dict(raw)
    log.info("OTP JS %s", filled)
    await _sleep(0.15)
    st = await _otp_state(tab)
    if st.get("val") != code:
        foc = await _focus_kind(tab, "code")
        typed = await _type_cdp(tab, code, enter=False)
        await _sleep(0.2)
        st = await _otp_state(tab)
        log.info("OTP CDP typed=%s focus=%s after=%s", typed, foc.get("ok"), st)
        if st.get("val") != code:
            raw2 = await _js(tab, FILL_OTP_JS.replace("%VAL%", json.dumps(code)))
            filled = _as_dict(raw2)
            st = await _otp_state(tab)
            log.info("OTP JS retry %s after=%s", filled, st)
    if st.get("val") != code:
        log.warning("OTP chưa dính vào ô (want=%s got=%s)", code, st.get("val"))
        return {"ok": False, "state": st, "filled": filled}
    await _sleep(0.35)
    clicked = await _click_continue(tab)
    log.info("OTP submit click=%s val=%s", clicked, st.get("val"))
    return {"ok": True, "state": st, "click": clicked, "filled": filled}


async def _click_resend(tab: Any) -> str:
    # Nút Resend trên màn login hay không bao giờ xuất hiện — đợi lâu chỉ
    # đốt ~18s/vòng; mã auto-gửi vốn tươi và ignore-list đã chặn mã cũ.
    for i in range(7):
        hit = str(await _js(tab, RESEND_JS) or "")
        if hit:
            log.info("Resend OTP: %s", hit)
            await _sleep(1.2)
            return hit
        if i == 0:
            log.info("Chờ nút Resend…")
        await _sleep(1.0)
    return ""


async def _type_cdp(tab: Any, text: str, *, enter: bool = False) -> bool:
    kb = getattr(tab, "keyboard", None)
    if kb is None:
        return False
    try:
        from pydoll.constants import Key
        from pydoll.protocol.input.types import KeyModifier

        await kb.press(Key.A, modifiers=KeyModifier.CTRL)
        await _sleep(0.04)
        await kb.press(Key.BACKSPACE)
    except Exception:
        await _js(
            tab,
            "(() => { const el = document.activeElement; if (el && el.select) el.select(); return 1; })()",
        )
    await _sleep(0.05)
    try:
        await kb.type_text(str(text), humanize=False, interval=0.035)
    except TypeError:
        await kb.type_text(str(text), humanize=False)
    if enter:
        try:
            from pydoll.constants import Key

            await kb.press(Key.ENTER)
        except Exception:
            await _press_enter(tab)
    return True


async def _fill(tab: Any, kind: str, val: str) -> int:
    script = SET_VALUE_JS.replace("%KIND%", json.dumps(kind)).replace("%VAL%", json.dumps(val))
    n = await _js(tab, script)
    try:
        filled = int(n or 0)
    except (TypeError, ValueError):
        filled = 1 if n else 0
    info = await _focus_kind(tab, kind)
    log.info(
        "Fill %s js=%s focus=%s inputs=%s",
        kind,
        filled,
        {k: info.get(k) for k in ("ok", "type", "ph", "ac", "max")},
        info.get("all"),
    )
    if kind == "code":
        await _type_cdp(tab, val, enter=True)
    return filled or (1 if info.get("ok") else 0)


async def _click_continue(tab: Any) -> str:
    hit = await _submit_form(tab)
    if hit:
        return str(hit)
    try:
        btns = await tab.find(tag_name="button", find_all=True, timeout=1, raise_exc=False)
    except Exception:
        btns = None
    if btns:
        if not isinstance(btns, list):
            btns = [btns]
        for el in btns:
            try:
                t = (getattr(el, "text", None) or "")
                if callable(t):
                    t = await t()
                t = str(t or "").strip().lower()
            except Exception:
                t = ""
            if t == "continue":
                try:
                    await el.click()
                    return "pydoll:continue"
                except Exception:
                    pass
    return await _click(tab, "continue", "create account", "next")


_LOGGED_PATHS = (
    "/folder",
    "/design/",
    "/your-apps",
    "/settings",
    "/home",
    "/templates",
    "/projects",
    "/onboarding",
    "/discover",
    "/query",
)


def _logged_in(url: str, body: str = "") -> bool:
    u = (url or "").lower()
    b = (body or "").lower()
    if "signup" in u or "/login" in u or "/redeem" in u:
        return False
    if "accounts.google" in u or "facebook.com" in u:
        return False
    if "canva.com" not in u:
        return False
    # trang marketing (chưa login) — đừng nhầm / hoặc /templates public
    if re_search(r"continue with email|log in or sign up|create your account", b):
        return False
    if any(p in u for p in _LOGGED_PATHS):
        return True
    return bool(
        re_search(
            r"create a design|recent designs|your designs|home dashboard|"
            r"template library|start designing",
            b,
        )
    )


_RESET_EMAIL_JS = r"""
(() => {
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 6 && r.height > 6 && !el.disabled;
  };
  const setNative = (el, v) => {
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, v); else el.value = v;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    try {
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: v, inputType: 'insertText' }));
    } catch (e) { el.dispatchEvent(new Event('input', { bubbles: true })); }
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const inputs = [...document.querySelectorAll('input')]
    .filter((i) => vis(i) && i.type !== 'hidden')
    .filter((i) => (i.type === 'email') || /email or phone/i.test(i.placeholder || ''));
  if (!inputs.length) return 0;
  setNative(inputs[0], %VAL%);
  inputs[0].focus();
  return 1;
})()
"""

_RESET_PW_JS = r"""
(() => {
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 6 && r.height > 6 && !el.disabled;
  };
  const setNative = (el, v) => {
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, v); else el.value = v;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    try {
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: v, inputType: 'insertText' }));
    } catch (e) { el.dispatchEvent(new Event('input', { bubbles: true })); }
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const inputs = [...document.querySelectorAll('input[type=password]')].filter(vis);
  inputs.forEach((i) => setNative(i, %VAL%));
  return inputs.length;
})()
"""

_RESET_CODE_JS = r"""
(() => {
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 6 && r.height > 6 && !el.disabled;
  };
  const setNative = (el, v) => {
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, v); else el.value = v;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    try {
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: v, inputType: 'insertText' }));
    } catch (e) { el.dispatchEvent(new Event('input', { bubbles: true })); }
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const inputs = [...document.querySelectorAll('input')]
    .filter((i) => vis(i) && /code/i.test(i.placeholder || '') && i.type !== 'hidden');
  if (!inputs.length) return 0;
  setNative(inputs[0], %VAL%);
  inputs[0].focus();
  return 1;
})()
"""


async def _set_account_password(
    tab: Any,
    email: str,
    password: str,
    config: dict[str, Any],
    wait_mail,
) -> str:
    """Đặt mật khẩu cho acc vừa reg qua /login/reset. Phiên còn đăng nhập nên
    Canva cho thẳng form mật khẩu mới, chỉ hỏi thêm mã xác minh gửi vào mail.
    Trả "ok" hoặc "skip:..."/"error:..."."""
    await tab.go_to("https://www.canva.com/login/reset")
    n = 0
    for _ in range(4):  # trang SPA render chậm — thử lại tới ~5s
        await _sleep(1.2)
        n = await _js(tab, _RESET_EMAIL_JS.replace("%VAL%", json.dumps(email)))
        if n:
            break
    log.info("Reset pw: fill email js=%s", n)
    if not n:
        return "skip:no_email_form"
    clicked = await _click(tab, "continue")
    log.info("Reset pw: submit email click=%s", clicked or "-")
    body = ""
    for _ in range(6):  # chờ form mật khẩu mới render (6 luồng load chậm hơn)
        await _sleep(1.5)
        body = (await _body(tab)).replace("\n", " ").lower()
        if "new password" in body:
            break
    if "new password" not in body:
        log.info("Reset pw: không thấy form mật khẩu mới | %s", body[:160])
        return "skip:no_pw_form"
    npw = await _js(tab, _RESET_PW_JS.replace("%VAL%", json.dumps(password)))
    log.info("Reset pw: fill %s ô mật khẩu", npw)
    if not npw:
        return "skip:no_pw_inputs"

    # Canva sắp gửi mã xác minh — chốt sẵn các mã đang nằm trong hộp để bỏ qua
    known: set[str] = set()
    try:
        from canreg.redeem import Acc, _tmail_known_codes

        known = await asyncio.to_thread(
            _tmail_known_codes, Acc(email=email, password=password), config
        )
    except Exception as e:
        log.info("Reset pw: known codes lỗi (bỏ qua): %s", e)

    clicked = await _click(tab, "set password")
    log.info("Reset pw: click set password=%s", clicked or "-")
    await _sleep(2.0)

    deadline = time.time() + 170
    tried_codes: set[str] = set(known)
    last_state = ""
    while time.time() < deadline:
        body = (await _body(tab)).replace("\n", " ")
        low = body.lower()
        cur = str(await _js(tab, "location.href") or "")
        if "/login/reset" not in cur.lower() and "let us know" not in low:
            log.info("Reset pw: thoát màn reset → %s", cur[:90])
            return "ok"
        # Trang thành công vẫn đứng yên trên /login/reset — nhận diện theo chữ
        if re_search(
            r"password (has been|was) (set|updated|changed|reset)"
            r"|successfully (reset|set|updated|changed) your password"
            r"|password successfully|you.?re? all set|all set!",
            low,
        ):
            log.info("Reset pw: trang xác nhận đặt mk | %s", body[:140])
            return "ok"
        if "can't send a verification code" in low or "for security reasons" in low:
            log.warning("Reset pw: Canva chặn gửi mã xác minh | %s", body[:180])
            return "error:verify_code_blocked"
        if "enter the code" in low or "let us know" in low:
            proof = await asyncio.to_thread(wait_mail) or {}
            code = str(proof.get("code") or "")
            if code and code not in tried_codes:
                tried_codes.add(code)
                n = await _js(tab, _RESET_CODE_JS.replace("%VAL%", json.dumps(code)))
                log.info("Reset pw: fill mã %s js=%s", code, n)
                # Enter không submit form Canva — phải bấm nút Continue
                hit = await _click(tab, "continue")
                log.info("Reset pw: submit mã click=%s", hit or "-")
                # Chờ Canva verify xong (2-12s) — resend vội sẽ huỷ hiệu lực
                # mã vừa nhập và rơi vào vòng lặp resend vô hạn.
                for _ in range(8):
                    await _sleep(1.5)
                    b2 = (await _body(tab)).replace("\n", " ").lower()
                    if re_search(
                        r"successfully (reset|set|updated|changed) your password"
                        r"|password (has been|was) (set|updated|changed|reset)",
                        b2,
                    ):
                        log.info("Reset pw: trang xác nhận đặt mk | %s", b2[:140])
                        return "ok"
                    cur2 = str(await _js(tab, "location.href") or "")
                    if "/login/reset" not in cur2.lower():
                        log.info("Reset pw: thoát màn reset → %s", cur2[:90])
                        return "ok"
                    if "incorrect" in b2 or "code you entered" in b2:
                        log.warning("Reset pw: mã %s bị từ chối", code)
                        break
                continue
            log.info("Reset pw: chưa có mã mới — thử resend")
            await _click(tab, "resend code", "resend")
            await _sleep(8.0)
            continue
        if "incorrect" in low or "code you entered" in low:
            log.warning("Reset pw: mã bị từ chối — resend lấy mã mới")
            await _click(tab, "resend code", "resend")
            await _sleep(8.0)
            continue
        state = f"{cur}|{low[:200]}"
        if state != last_state:
            log.info("Reset pw: chờ trang xử lý | %s | %s", cur[:80], low[:160])
            last_state = state
        await _sleep(3.0)
    return "error:timeout"


async def register_browser(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail,
    display_name: str = "",
) -> dict[str, Any]:
    from canreg.config import resolve_display_name

    name = (display_name or resolve_display_name(config)).strip()
    signup = str(config.get("signup_url") or SIGNUP_URL)
    browser = None
    try:
        browser, tab = await open_browser(config)
        log.info("Mở %s", signup)
        await tab.go_to(signup)
        await _sleep(1.5)
        await _wait_cf(tab)
        info = await _js(tab, PAGE_INFO_JS)
        log.info("UI snapshot: %s", str(info)[:400])

        clicked = await _click(tab, "continue with email", "sign up with email", "use email")
        if clicked:
            log.info("Click: %s", clicked)
            st = await _wait_stage(tab, not_in=("landing",), seconds=8)
            log.info("Sau continue-with-email stage=%s", st)

        filled = await _fill(tab, "email", email)
        log.info("Fill email fields=%s", filled)
        if not filled:
            await dump_network(tab, "no_email_fields")
            return {"ok": False, "status": "error:no_signup_fields"}
        await _sleep(0.45)
        submitted = await _click_continue(tab)
        log.info("Submit email: %s", submitted or "(enter)")
        if not submitted:
            await _press_enter(tab)
        stage = await _wait_stage(tab, not_in=("email", "landing"), seconds=12)
        body = await _body(tab)
        url = str(await _js(tab, "location.href") or "")
        log.info("Sau email stage=%s | %s", stage, body.replace("\n", " ")[:200])
        await dump_network(tab, "after_email")

        proof: dict[str, str] = {}
        spent = False
        otp_accepted = False
        for step in range(1, 9):
            raise_if_stop()
            body = await _body(tab)
            url = str(await _js(tab, "location.href") or "")
            stage = _stage(url, body)
            log.info("Step %s stage=%s url=%s", step, stage, url[:80])
            if stage == "flagged":
                return {
                    "ok": False,
                    "status": "error:email_flagged",
                    "url": url,
                    "spent_email": spent,
                }
            if stage == "home" or _logged_in(url, body):
                break
            if stage in ("landing", "email"):
                await _fill(tab, "email", email)
                await _sleep(0.3)
                hit = await _click_continue(tab)
                if not hit:
                    await _press_enter(tab)
                await _wait_stage(tab, not_in=("email", "landing"), seconds=8)
                continue
            if stage == "name":
                n = await _fill(tab, "name", name)
                log.info("Fill name=%s (%s)", n, name)
                await _sleep(0.35)
                clicked = await _click_continue(tab)
                log.info("Submit name: %s", clicked)
                if not clicked:
                    await _press_enter(tab)
                await _wait_stage(tab, not_in=("name",), seconds=10)
                continue
            if stage == "otp":
                spent = True
                if not proof.get("code") and not proof.get("link"):
                    log.info("Đã tới màn OTP — chờ mail…")
                    proof = wait_mail() or {}
                if proof.get("link") and not proof.get("code"):
                    log.info("Mở link verify %s", proof["link"][:90])
                    await tab.go_to(proof["link"])
                    await _sleep(5)
                    continue
                if not proof.get("code"):
                    return {
                        "ok": False,
                        "status": "error:otp_timeout",
                        "url": url,
                        "spent_email": True,
                    }
                put = await _fill_otp(tab, proof["code"])
                nxt = await _wait_stage(tab, not_in=("otp",), seconds=20)
                log.info("Sau OTP stage=%s fill_ok=%s", nxt, put.get("ok"))
                body_after = await _body(tab)
                if nxt == "flagged" or _stage(url, body_after) == "flagged":
                    log.warning("Canva chặn sau OTP: %s", body_after.replace("\n", " ")[:180])
                    return {
                        "ok": False,
                        "status": "error:email_flagged",
                        "url": url,
                        "spent_email": True,
                        "detail": "security_block",
                    }
                if nxt != "otp":
                    # OTP đúng → Canva hay đổ /templates (không phải /folder)
                    otp_accepted = True
                    break
                if nxt == "otp":
                    st = await _otp_state(tab)
                    body_now = (await _body(tab)).replace("\n", " ")[:240]
                    log.warning("OTP còn trên form state=%s | %s", st, body_now)
                    # mã sai → bỏ mã cũ, lấy mail mới nhất (không nhập lại cùng mã)
                    if st.get("bad_err"):
                        log.warning("Mã %s SAI — bỏ, chờ mail mới nhất", proof.get("code"))
                        await dump_network(tab, "otp_wrong")
                        await _click_resend(tab)
                        proof = {}
                        continue
                    if not put.get("ok") or st.get("empty_err") or not st.get("val"):
                        log.warning("Ô OTP trống — điền lại mã %s", proof["code"])
                        put = await _fill_otp(tab, proof["code"])
                        nxt = await _wait_stage(tab, not_in=("otp",), seconds=20)
                        if nxt != "otp":
                            otp_accepted = True
                            break
                    info = await _js(tab, PAGE_INFO_JS)
                    log.warning("OTP %s chưa nhận — Resend | %s", proof["code"], str(info)[:220])
                    await dump_network(tab, "otp_stuck")
                    await _click_resend(tab)
                    proof = {}
                    continue
            picked = await _click(
                tab, "skip", "maybe later", "not now", "get started", "start designing", "continue"
            )
            log.info("Onboard click=%s", picked or "-")
            await _sleep(1.4)

        cur = str(await _js(tab, "location.href") or "")
        body = await _body(tab)
        ok = _logged_in(cur, body) or _stage(cur, body) == "home"
        if not ok and otp_accepted:
            u = cur.lower()
            if "canva.com" in u and "signup" not in u and "/login" not in u:
                ok = True
                log.info("OTP đã nhận, URL post-signup %s → success", cur[:80])
        offer: dict[str, Any] = {}
        if ok and config.get("offer_check_after_reg", True):
            # Acc mới lúc nào cũng Free — bỏ qua khi chạy tốc độ (tiết kiệm 1 page load)
            try:
                from canreg.offers import offer_from_page

                try:
                    await tab.go_to("https://www.canva.com/settings/billing")
                    await _sleep(1.2)
                    cur = str(await _js(tab, "location.href") or "")
                    body = await _body(tab)
                except Exception:
                    pass
                offer = offer_from_page(cur, body)
            except Exception:
                offer = {}
        status = "success" if ok else "error:signup_incomplete"
        if ok and offer.get("summary") and offer.get("summary") not in ("free", "no_offer"):
            status = f"success:{offer.get('summary')}"
        # Đặt mật khẩu cho acc (mặc định bật, tắt bằng set_password_after_reg=false)
        if ok and config.get("set_password_after_reg") is not False:
            try:
                pw_status = await _set_account_password(
                    tab, email, password, config, wait_mail
                )
            except Exception as e:
                pw_status = f"error:{e}"
            log.info("Set password %s → %s", email, pw_status)
        # Bắt cookie phiên đăng ký ngay khi còn mở trình duyệt — bước redeem
        # kế tiếp inject lại là đã login, khỏi đi qua màn OTP thứ hai.
        canva_cookies: list[dict[str, Any]] = []
        if ok:
            try:
                # pydoll trả Cookie là TypedDict (plain dict), không phải object.
                for c in await tab.get_cookies() or []:
                    get = c.get if isinstance(c, dict) else (
                        lambda k, _c=c, d=None: getattr(_c, k, d)
                    )
                    cname = str(get("name", "") or "")
                    if not cname:
                        continue
                    item: dict[str, Any] = {"name": cname, "value": str(get("value", "") or "")}
                    for attr in ("domain", "path", "secure", "httpOnly", "sameSite", "expires"):
                        val = get(attr)
                        if val not in (None, "", False):
                            item[attr] = val
                    canva_cookies.append(item)
                log.info("Cookie capture %s: %s cookie", email, len(canva_cookies))
            except Exception as e:
                log.info("Cookie capture lỗi (bỏ qua): %s", e)
        log.info("Done url=%s → %s", cur[:80], status)
        return {
            "ok": ok,
            "status": status,
            "url": cur,
            "offer": offer,
            "proof": proof,
            "spent_email": spent or ok,
            "otp_accepted": otp_accepted,
            "cookies": canva_cookies,
            "session": {"url": cur, "name": name, "email": email},
        }
    finally:
        await close_browser(
            browser,
            port=(config.get("chrome_debug_port") if config.get("chrome_parallel") else None),
        )
