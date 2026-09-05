"""Chrome signup for HeyGen (pydoll), same stack as grok_tool."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

from heyreg.log import log
from heyreg.paths import DATA, ROOT
from heyreg.stop import raise_if_stop

SIGNUP_URL = "https://auth.heygen.com/signup"
APP_URL = "https://app.heygen.com/"


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


def kill_heygen_chrome() -> int:
    """Kill only HeyGen automation Chrome (not user Chrome, not Grok :9333)."""
    import subprocess

    ps = r"""
$ErrorActionPreference='SilentlyContinue'
$n = 0
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -match 'Heygen\\chrome_runs' -or
    $_.CommandLine -match 'Heygen/chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=9444'
  )
} | ForEach-Object {
  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ } catch {}
}
Write-Output $n
"""
    try:
        hide = {}
        try:
            from heyreg.paths import ensure_grok_on_path
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
            log.info("Don Chrome HeyGen cu: killed≈%s", n)
        return n
    except Exception as e:
        log.debug("kill heygen chrome: %s", e)
        return 0


def park_heygen_chrome(config: dict[str, Any]) -> None:
    """Giong Grok: keo cua so ra ngoai man + minimize, khong cuop focus."""
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
public class HgWin {{
  [DllImport("user32.dll")] public static extern bool SetWindowPos(
    IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}}
"@
$flags = [uint32]0x0015
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {{
  $_.CommandLine -and (
    $_.CommandLine -match 'Heygen\\\\chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=9444'
  )
}} | ForEach-Object {{
  $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
  if ($p -and $p.MainWindowHandle -ne [IntPtr]::Zero) {{
    [HgWin]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, {x}, {y}, 0, 0, $flags) | Out-Null
    [HgWin]::ShowWindowAsync($p.MainWindowHandle, 7) | Out-Null
  }}
}}
"""
    try:
        hide = {}
        try:
            from heyreg.paths import ensure_grok_on_path
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
        log.info("Chrome HeyGen parked off-screen (khong cuop man hinh)")
    except Exception as e:
        log.debug("park chrome: %s", e)


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
    from heyreg.paths import ensure_grok_on_path

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

    kill_heygen_chrome()
    await _sleep(0.6)
    port = int(config.get("chrome_debug_port") or 9444)
    if _port_busy(port):
        for cand in range(port, port + 40):
            if not _port_busy(cand):
                port = cand
                config["chrome_debug_port"] = port
                log.info("Port ban — dung %s", port)
                break
    last_err: Exception | None = None
    for attempt in range(1, 4):
        opt = _chrome_options(config, port)
        log.info("Chrome start debug_port=%s (off-screen, lan %s)", port, attempt)
        try:
            browser = Chrome(options=opt, connection_port=port)
            tab = await browser.start()
            try:
                from grokreg.browser.anti_flag import enable_stealth_auto

                await enable_stealth_auto(tab, config.get("_fingerprint") or {})
            except Exception as e:
                log.debug("stealth auto: %s", e)
            park_heygen_chrome(config)
            await _sleep(0.15)
            park_heygen_chrome(config)
            return browser, tab
        except Exception as e:
            last_err = e
            log.warning("Chrome start fail lan %s: %s", attempt, e)
            kill_heygen_chrome()
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
    kill_heygen_chrome()


async def dump_network(tab: Any, tag: str) -> None:
    """Best-effort: store current URL + HTML snippet for protocol tuning."""
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


FILL_FORM_JS = r"""
(() => {
  const email = %EMAIL%;
  const password = %PASSWORD%;
  const setNative = (el, val) => {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, val);
    else el.value = val;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };
  const inputs = [...document.querySelectorAll('input')];
  const emailEl = inputs.find(i =>
    /email|user/i.test(i.type + i.name + i.id + i.placeholder + (i.autocomplete||''))
  ) || inputs.find(i => i.type === 'text' || i.type === 'email');
  const passEl = inputs.find(i => i.type === 'password')
    || inputs.find(i => /pass/i.test(i.name + i.id + i.placeholder));
  let n = 0;
  if (setNative(emailEl, email)) n++;
  if (setNative(passEl, password)) n++;
  return n;
})()
"""

PAGE_INFO_JS = r"""
(() => {
  const texts = [...document.querySelectorAll('button, a, [role=button], input')]
    .slice(0, 40)
    .map(el => {
      const t = (el.innerText || el.textContent || el.placeholder || el.type || '').trim();
      return t.slice(0, 50);
    })
    .filter(Boolean);
  return JSON.stringify({
    url: location.href,
    title: document.title,
    body: (document.body && document.body.innerText || '').slice(0, 1400),
    controls: texts,
  });
})()
"""

CLICK_EMAIL_SIGNUP_JS = r"""
(() => {
  const texts = [
    'sign up with email', 'continue with email', 'use email',
    'send code', 'send link', 'sign up', 'create account',
  ];
  const nodes = [...document.querySelectorAll('button, a, [role=button]')];
  for (const el of nodes) {
    const t = (el.innerText || el.textContent || '').trim().toLowerCase();
    if (!t || t.length > 48) continue;
    if (texts.some(x => t === x || t.includes(x))) {
      el.click();
      return t.slice(0, 40);
    }
  }
  return '';
})()
"""

SUBMIT_JS = r"""
(() => {
  const prefer = [
    'send a secure magic link', 'send magic link', 'send code', 'send link',
    'verify', 'sign in', 'log in',
  ];
  const deny = /google|apple|sso|facebook|github|microsoft/;
  const btns = [...document.querySelectorAll('button, [type=submit], [role=button], a')];
  const label = (el) => (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
  for (const want of prefer) {
    const hit = btns.find(el => {
      const t = label(el);
      return t && t.length < 60 && t.includes(want) && !deny.test(t);
    });
    if (hit) { hit.click(); return label(hit).slice(0, 50); }
  }
  return '';
})()
"""

FILL_CODE_JS = r"""
(() => {
  const code = %CODE%;
  const inputs = [...document.querySelectorAll('input')];
  const el = inputs.find(i =>
    /otp|code|verif|pin/i.test(i.name + i.id + i.placeholder + i.autocomplete + i.inputMode)
  ) || inputs.find(i => (i.maxLength && i.maxLength <= 8) || i.inputMode === 'numeric');
  if (!el) return 0;
  const proto = window.HTMLInputElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
  if (desc && desc.set) desc.set.call(el, code);
  else el.value = code;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
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
  const deny = /google|apple|sso|facebook|privacy|terms|english|creator|pro\b|premium|upgrade|subscribe|checkout|trial|stripe|pricing|choose creator|choose pro/;
  const nextRe = /choose free|continue|next|skip|done|finish|get started|confirm|let'?s go|tiếp|bỏ qua|hoàn tất|bắt đầu|→/;
  const optionRe = /choose free|other|khác|marketer|marketing|content|sales|education|1-10|11-50|just me|individual|freelancer|personal|hobby/;
  let acted = [];
  const btns = [...document.querySelectorAll('button, [role=button], a, [role=option], label')].filter(vis);
  const prefer = ['choose free', 'skip', 'individual', 'just me', 'other'];
  for (const want of prefer) {
    const hit = btns.find(el => {
      const t = txt(el).toLowerCase();
      return t && t.length < 40 && t.includes(want) && !deny.test(t);
    });
    if (hit) { hit.click(); return 'pick:' + txt(hit).slice(0, 32); }
  }
  const cards = [...document.querySelectorAll(
    'button, [role=option], [role=radio], [role=button], label, [class*="card"], [class*="option"], [class*="tile"]'
  )].filter(vis);
  const opt = cards.find(el => {
    const t = txt(el);
    return t && t.length < 48 && optionRe.test(t) && !deny.test(t) && !nextRe.test(t);
  });
  if (opt) { opt.click(); acted.push('opt:' + txt(opt).slice(0, 28)); }
  const nxt = btns.find(el => {
    const t = txt(el);
    return t && t.length < 28 && nextRe.test(t) && !deny.test(t) && !/choose free/i.test(t);
  });
  if (nxt) { nxt.click(); acted.push('next:' + txt(nxt).slice(0, 20)); }
  return acted.join('|') || '';
})()
"""

SESSION_JS = r"""
(() => {
  const cookies = document.cookie || '';
  const ls = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const v = localStorage.getItem(k) || '';
      if (/token|auth|session|user/i.test(k) && v.length < 4000) ls[k] = v;
    }
  } catch (e) {}
  return JSON.stringify({ url: location.href, cookie_len: cookies.length, ls });
})()
"""


async def register_browser(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail,
) -> dict[str, Any]:
    signup = str(config.get("signup_url") or SIGNUP_URL)
    browser = None
    try:
        browser, tab = await open_browser(config)
        log.info("Mo %s", signup)
        await tab.go_to(signup)
        await _sleep(3.5)
        info = await _js(tab, PAGE_INFO_JS)
        log.info("UI snapshot: %s", str(info)[:400])

        clicked = await _js(tab, CLICK_EMAIL_SIGNUP_JS)
        if clicked:
            log.info("Click: %s", clicked)
            await _sleep(1.0)

        filled = await _js(
            tab,
            FILL_FORM_JS.replace("%EMAIL%", json.dumps(email)).replace(
                "%PASSWORD%", json.dumps(password)
            ),
        )
        log.info("Fill email/password fields=%s", filled)
        if not filled:
            await dump_network(tab, "no_email_fields")
            return {"ok": False, "status": "error:no_signup_fields"}

        from heyreg.turnstile import inject_token, kick_solver, solve_token

        kick_solver(config)
        try:
            ts_token = await asyncio.to_thread(solve_token, config)
            await inject_token(tab, ts_token, _js)
        except Exception as e:
            log.warning("Turnstile inject fail: %s — van thu gui", e)

        await _sleep(0.5)
        submitted = await _js(tab, SUBMIT_JS)
        log.info("Submit/send_code: %s", submitted)
        for _ in range(8):
            await _sleep(1.0)
            body_now = str(await _js(tab, "document.body ? document.body.innerText.slice(0,900) : ''") or "")
            if re_search(r"sending|verifying", body_now) and not re_search(
                r"check your email|sent|inbox|flagged|spam", body_now
            ):
                continue
            break
        info2 = await _js(tab, PAGE_INFO_JS)
        log.info("UI after submit: %s", str(info2)[:700])
        await dump_network(tab, "after_submit")

        url = str(await _js(tab, "location.href") or "")
        html = str(await _js(tab, "document.body ? document.body.innerText.slice(0,2000) : ''") or "")
        if re_search(r"flagged as potential spam|try another email", html):
            return {"ok": False, "status": "error:email_flagged", "url": url, "detail": "HeyGen chan temp mail"}
        if re_search(r"suspicious|400562|verify again", html):
            return {"ok": False, "status": "error:turnstile_flagged", "url": url, "detail": html[:240]}

        need_verify = bool(
            re_search(r"verif|code|inbox|confirm|check your email|sent|magic link", html + url)
        )

        proof: dict[str, str] = {}
        if need_verify or "signup" in url.lower() or "verify" in url.lower():
            log.info("Cho mail xac minh…")
            proof = wait_mail() or {}
            if not proof:
                html2 = str(await _js(tab, "document.body ? document.body.innerText.slice(0,800) : ''") or "")
                if re_search(r"flagged|suspicious|400562", html2):
                    return {"ok": False, "status": "error:turnstile_flagged", "url": url}

        if proof.get("link"):
            log.info("Mo link verify %s", proof["link"][:90])
            await tab.go_to(proof["link"])
            await _sleep(6)
            cur0 = str(await _js(tab, "location.href") or "")
            if "app.heygen.com" in cur0:
                try:
                    await tab.go_to("https://app.heygen.com/home")
                    await _sleep(3)
                except Exception:
                    pass
        elif proof.get("code"):
            n = await _js(tab, FILL_CODE_JS.replace("%CODE%", json.dumps(proof["code"])))
            log.info("Fill OTP fields=%s code=%s", n, proof["code"])
            await _sleep(0.3)
            await _js(tab, SUBMIT_JS)
            await _sleep(2.5)

        for i in range(12):
            raise_if_stop()
            cur = str(await _js(tab, "location.href") or "")
            if "checkout.stripe.com" in cur or "stripe.com/c/pay" in cur:
                log.warning("Roi Stripe checkout — acc da tao, quay ve /home")
                try:
                    await tab.go_to("https://app.heygen.com/home")
                    await _sleep(3)
                except Exception:
                    pass
                break
            body = str(await _js(tab, "document.body ? document.body.innerText.slice(0,400) : ''") or "")
            btns = await _js(
                tab,
                "JSON.stringify([...document.querySelectorAll('button,[role=button]')].map(b=>(b.innerText||'').trim()).filter(Boolean).slice(0,18))",
            )
            log.info("Onboard step %s url=%s | %s | btns=%s", i + 1, cur[:80], body.replace("\n", " ")[:100], str(btns)[:180])
            if _onboard_done(cur):
                break
            picked = await _js(tab, ONBOARD_JS)
            log.info("Onboarding click: %s", picked or "(none)")
            if not picked and i > 2:
                try:
                    await tab.go_to("https://app.heygen.com/home")
                    await _sleep(2)
                except Exception:
                    pass
                break
            await _sleep(1.4)

        sess_raw = await _js(tab, SESSION_JS)
        sess = {}
        try:
            sess = json.loads(sess_raw) if isinstance(sess_raw, str) else (sess_raw or {})
        except Exception:
            sess = {"raw": str(sess_raw)[:200]}
        url = str(sess.get("url") or await _js(tab, "location.href") or "")
        cookie_len = int(sess.get("cookie_len") or 0)
        logged_in = _onboard_done(url) or (
            "app.heygen.com" in url
            and "auth.heygen.com" not in url
            and "signup" not in url
            and "login" not in url
        )
        if "checkout.stripe.com" in url:
            logged_in = True
        ok = bool(logged_in)
        if ok and "/onboarding" in url:
            status = "success_onboarding"
        elif ok:
            status = "success"
        else:
            status = "error:signup_incomplete"
        log.info("Done url=%s cookies=%s → %s", url[:80], cookie_len, status)
        return {
            "ok": ok,
            "status": status,
            "url": url,
            "session": sess,
            "proof": proof,
        }
    finally:
        await close_browser(browser)


def _onboard_done(url: str) -> bool:
    u = (url or "").lower()
    if "checkout.stripe.com" in u:
        return False
    if "auth.heygen.com" in u or "signup" in u:
        return False
    if "app.heygen.com" not in u:
        return False
    if "/onboarding" in u:
        return False
    return any(p in u for p in ("/home", "/dashboard", "/explore", "/avatar", "/create", "/workspace"))


def re_search(pat: str, text: str) -> bool:
    import re

    return bool(re.search(pat, text or "", re.I))
