"""Chrome signup for Netflix (pydoll). Stops at the payment / plan wall."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from nfreg.log import log
from nfreg.paths import DATA, ROOT
from nfreg.stop import raise_if_stop

SIGNUP_URL = "https://www.netflix.com/signup"
# Official computer flow (help.netflix.com/node/112419):
# signup → choose plan (planform) → email/password → payment. Stop at payment only.
PAYMENT_RE = re.compile(
    r"/signup/payment|/simpleSetup/payment|"
    r"credit or debit card|add payment method|billing information|"
    r"set up your payment|thêm phương thức thanh toán",
    re.I,
)
PLAN_RE = re.compile(
    r"planform|/signup/plan|choose.?plan|select.?plan|step 1 of|step 2 of|"
    r"\b(mobile|basic|standard|premium|ads)\b",
    re.I,
)
CAPTCHA_RE = re.compile(
    r"recaptcha|hcaptcha|arkose|funcaptcha|unusual activity|robot|captcha",
    re.I,
)

FILL_EMAIL_JS = r"""
(() => {
  const email = %EMAIL%;
  const setNative = (el, val) => {
    if (!el) return false;
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
  const inputs = [...document.querySelectorAll('input')];
  const emailEl = inputs.find(i =>
    /email|user/i.test((i.type||'') + (i.name||'') + (i.id||'') + (i.placeholder||'') + (i.autocomplete||''))
  ) || inputs.find(i => i.type === 'email' || i.type === 'text');
  return setNative(emailEl, email) ? 1 : 0;
})()
"""

FILL_PASSWORD_JS = r"""
(() => {
  const password = %PASSWORD%;
  const setNative = (el, val) => {
    if (!el) return false;
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
  const passEl = [...document.querySelectorAll('input')].find(i =>
    i.type === 'password' || /pass/i.test((i.name||'') + (i.id||'') + (i.placeholder||''))
  );
  return setNative(passEl, password) ? 1 : 0;
})()
"""

CLICK_PASSWORD_INSTEAD_JS = r"""
(() => {
  // help.netflix.com/node/529303577956964 — magic-link signup can switch to password
  const nodes = [...document.querySelectorAll('button, a, [role=button], span')];
  for (const el of nodes) {
    const t = (el.innerText || el.textContent || '').trim().toLowerCase();
    if (!t || t.length > 48) continue;
    if (t.includes('create password instead') || t.includes('use password instead')
        || t.includes('tạo mật khẩu') || t.includes('dùng mật khẩu')) {
      el.click();
      return t.slice(0, 48);
    }
  }
  return '';
})()
"""

CLICK_PLAN_JS = r"""
(() => {
  const prefer = [
    'standard', 'premium', 'basic', 'mobile', 'ads', 'with ads',
    'get started', 'see the plans', 'choose plan', 'chọn gói',
  ];
  const deny = /google|apple|facebook|privacy|terms|help|card|paypal/;
  const nodes = [...document.querySelectorAll('button, [role=button], label, a, [class*="plan"]')];
  const label = (el) => (el.innerText || el.textContent || '').trim().toLowerCase();
  for (const want of prefer) {
    const hit = nodes.find(el => {
      const t = label(el);
      return t && t.length < 80 && t.includes(want) && !deny.test(t);
    });
    if (hit) { hit.click(); return label(hit).slice(0, 50); }
  }
  return '';
})()
"""

CLICK_NEXT_JS = r"""
(() => {
  const prefer = [
    'create password instead', 'get started', 'start', 'next', 'continue',
    'sign up', 'create account', 'tiếp', 'bắt đầu',
  ];
  const deny = /google|apple|facebook|privacy|terms|help|card|paypal/;
  const btns = [...document.querySelectorAll('button, [type=submit], [role=button], a')];
  const label = (el) => (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
  for (const want of prefer) {
    const hit = btns.find(el => {
      const t = label(el);
      return t && t.length < 40 && t.includes(want) && !deny.test(t);
    });
    if (hit) { hit.click(); return label(hit).slice(0, 50); }
  }
  const submit = document.querySelector('button[type=submit], input[type=submit]');
  if (submit) { submit.click(); return 'submit'; }
  return '';
})()
"""

FILL_CODE_JS = r"""
(() => {
  const code = %CODE%;
  const inputs = [...document.querySelectorAll('input')];
  const el = inputs.find(i =>
    /otp|code|verif|pin/i.test((i.name||'') + (i.id||'') + (i.placeholder||'') + (i.autocomplete||'') + (i.inputMode||''))
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
    $_.CommandLine -match 'netflix\\chrome_runs' -or
    $_.CommandLine -match 'netflix/chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=95'
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
            log.info("Dọn Chrome Netflix cũ: killed≈%s", n)
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
    from nfreg.paths import ensure_grok_on_path

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
    port = int(config.get("chrome_debug_port") or 9544)
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
        log.info("Mở %s", signup)
        await tab.go_to(signup)
        await _sleep(3.5)

        filled_e = 0
        filled_p = 0
        url = signup
        html = ""
        for step in range(1, 12):
            info = _parse_info(await _js(tab, PAGE_INFO_JS))
            url = str(info.get("url") or url)
            html = str(info.get("body") or "")
            blob = f"{url} {html}"
            log.info("UI step %s: %s | %s", step, url.split("?")[0], html[:180].replace("\n", " / "))

            if PAYMENT_RE.search(blob):
                await dump_network(tab, "payment_wall")
                break
            if CAPTCHA_RE.search(blob) or await _js(
                tab,
                "!!(document.querySelector('#recaptcha, iframe[src*=\"recaptcha\"], iframe[src*=\"hcaptcha\"], iframe[src*=\"arkoselabs\"]'))",
            ):
                log.warning("Netflix captcha — bỏ acc này")
                return {"ok": False, "status": "error:skip_captcha", "url": url, "detail": html[:180]}

            pw_alt = await _js(tab, CLICK_PASSWORD_INSTEAD_JS)
            if pw_alt:
                log.info("Click: %s", pw_alt)
                await _sleep(1.2)
                continue

            if re.search(r"check your email|sign-up link|we sent (a |you )?(code|link)|enter the code", html, re.I):
                break

            # Step 1 intro: "Choose your plan" + Next (no Standard/Premium cards yet)
            if re.search(r"choose your plan|step 1 of", html, re.I) and not re.search(
                r"\b(standard|premium|basic|mobile)\b", html, re.I
            ):
                clicked = await _js(tab, CLICK_NEXT_JS)
                log.info("Click plan-intro: %s", clicked)
                await _sleep(2.2)
                continue

            if re.search(r"\b(standard|premium|basic|mobile)\b", html, re.I):
                picked = await _js(tab, CLICK_PLAN_JS)
                if picked:
                    log.info("Chọn gói (không thanh toán): %s", picked)
                    await _sleep(1.2)
                clicked = await _js(tab, CLICK_NEXT_JS)
                if clicked:
                    log.info("Click: %s", clicked)
                await _sleep(2.2)
                continue

            n_e = await _js(tab, FILL_EMAIL_JS.replace("%EMAIL%", json.dumps(email)))
            n_p = await _js(tab, FILL_PASSWORD_JS.replace("%PASSWORD%", json.dumps(password)))
            if n_e:
                filled_e = int(n_e or 0) or filled_e
                log.info("Fill email=%s", n_e)
            if n_p:
                filled_p = int(n_p or 0) or filled_p
                log.info("Fill password=%s", n_p)
            if n_e or n_p:
                clicked = await _js(tab, CLICK_NEXT_JS)
                if clicked:
                    log.info("Click: %s", clicked)
                await _sleep(2.5)
                continue

            clicked = await _js(tab, CLICK_NEXT_JS)
            if clicked:
                log.info("Click: %s", clicked)
                await _sleep(2.0)
                continue
            break

        url = str(await _js(tab, "location.href") or url)
        html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or html)
        await dump_network(tab, "after_wizard")

        if PAYMENT_RE.search(url + " " + html):
            log.warning("Tới cổng thanh toán / chọn gói — dừng. Không điền card.")
            return {
                "ok": True,
                "status": "need_payment",
                "url": url,
                "detail": "need_payment",
                "session": {"email": email, "url": url},
            }

        if re.search(r"check your email|sign-up link|we sent (a |you )?(code|link)|enter the code", html + url, re.I):
            log.info("Chờ mail xác minh…")
            proof = wait_mail() or {}
            if proof.get("link"):
                await tab.go_to(proof["link"])
                await _sleep(4)
            elif proof.get("code"):
                n = await _js(tab, FILL_CODE_JS.replace("%CODE%", json.dumps(proof["code"])))
                log.info("Fill OTP fields=%s", n)
                await _js(tab, CLICK_NEXT_JS)
                await _sleep(3)
            url = str(await _js(tab, "location.href") or "")
            html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2000) : ''") or "")
            await dump_network(tab, "after_verify")
            if PAYMENT_RE.search(url + " " + html):
                return {
                    "ok": True,
                    "status": "need_payment",
                    "url": url,
                    "detail": "need_payment",
                    "session": {"email": email, "url": url},
                }

        if not filled_e and not filled_p:
            return {"ok": False, "status": "error:no_signup_fields", "url": url}

        return {
            "ok": False,
            "status": "error:signup_incomplete",
            "url": url,
            "detail": (html or "")[:240],
            "session": {"email": email, "url": url},
        }
    finally:
        await close_browser(browser)
