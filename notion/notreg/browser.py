"""Chrome signup for Notion (pydoll) — email magic link / login code."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from notreg.log import log
from notreg.paths import DATA, ROOT
from notreg.stop import raise_if_stop

SIGNUP_URL = "https://www.notion.so/signup"
APP_RE = re.compile(
    r"notion\.(?:so|com)/(?:[^/]+/)?(?:onboarding|product|meet|my|workspace)|app\.notion\.com/(?!signup|login)",
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
    /email|user/i.test((i.type||'') + (i.name||'') + (i.id||'') + (i.placeholder||'') + (i.autocomplete||''))
  ) || inputs.find(i => i.type === 'email' || i.type === 'text');
  return setNative(emailEl, email) ? 1 : 0;
})()
"""

CLICK_EMAIL_JS = r"""
(() => {
  const texts = ['continue with email', 'sign up with email', 'work email'];
  const deny = /google|apple|sso|facebook|passkey|saml|microsoft/;
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

RESEND_JS = r"""
(() => {
  const prefer = ['resend code', 'resend', 'send a new code', "didn't get a code", 'send again'];
  const btns = [...document.querySelectorAll('button, [role=button], a')];
  const label = (el) => (el.innerText || el.textContent || '').trim().toLowerCase();
  for (const want of prefer) {
    const hit = btns.find(el => {
      const t = label(el);
      return t && t.length < 48 && t.includes(want);
    });
    if (hit) { hit.click(); return label(hit).slice(0, 40); }
  }
  return '';
})()
"""

SUBMIT_JS = r"""
(() => {
  const prefer = ['continue with email', 'send login code', 'send code', 'continue', 'sign up', 'log in'];
  const deny = /google|apple|sso|facebook|passkey|saml|microsoft/;
  const btns = [...document.querySelectorAll('button, [type=submit], [role=button], a')];
  const label = (el) => (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
  for (const want of prefer) {
    const hit = btns.find(el => {
      const t = label(el);
      return t && t.length < 60 && t.includes(want) && !deny.test(t);
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
  const code = String(%CODE% || '');
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 4 && r.height > 4;
  };
  const setNative = (el, val) => {
    el.focus();
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    const prev = el.value;
    if (desc && desc.set) desc.set.call(el, val);
    else el.value = val;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const inputs = [...document.querySelectorAll('input')].filter(vis)
    .filter(i => i.type !== 'email' && i.type !== 'password' && i.type !== 'hidden');
  const boxes = inputs.filter(i => i.maxLength === 1 || (i.inputMode === 'numeric' && (i.maxLength || 1) <= 2));
  if (boxes.length >= 4 && code.length >= boxes.length) {
    boxes.slice(0, code.length).forEach((el, i) => setNative(el, code[i]));
    return boxes.length;
  }
  const el = inputs.find(i =>
    /otp|code|verif|pin|login code/i.test((i.name||'') + (i.id||'') + (i.placeholder||'') + (i.autocomplete||'') + (i.ariaLabel||''))
  ) || inputs.find(i => (i.maxLength && i.maxLength >= 4 && i.maxLength <= 8) || i.inputMode === 'numeric');
  if (!el) return 0;
  setNative(el, code);
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
  const deny = /google|apple|facebook|privacy|terms|upgrade|subscribe|pricing|billing|card|skip to content|skip to main/;
  const nextRe = /continue|next|done|finish|get started|for myself|just me|personal|tiếp|bỏ qua/;
  const btns = [...document.querySelectorAll('button, [role=button], a, div[role=button]')].filter(vis);
  const prefer = ['for myself', 'just me', 'personal', 'continue'];
  for (const want of prefer) {
    const hit = btns.find(el => {
      const t = txt(el).toLowerCase();
      return t && t.length < 40 && t.includes(want) && !deny.test(t);
    });
    if (hit) { hit.click(); return 'pick:' + txt(hit).slice(0, 32); }
  }
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
  let token_v2 = '';
  for (const part of cookies.split(';')) {
    const [k, ...rest] = part.split('=');
    if ((k || '').trim() === 'token_v2') token_v2 = rest.join('=').trim();
  }
  return JSON.stringify({ url: location.href, cookie_len: cookies.length, token_v2: token_v2 });
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
    $_.CommandLine -match 'notion\\chrome_runs' -or
    $_.CommandLine -match 'notion/chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=97'
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
            log.info("Dọn Chrome Notion cũ: killed≈%s", n)
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
    from notreg.paths import ensure_grok_on_path

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
    port = int(config.get("chrome_debug_port") or 9744)
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


async def _cdp_token_v2(tab: Any) -> str:
    cookies: list[dict[str, Any]] = []

    def _extract(raw: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            inner = raw.get("result") if "result" in raw else raw
            cl = inner.get("cookies") if isinstance(inner, dict) else None
            if isinstance(cl, list):
                out.extend([c for c in cl if isinstance(c, dict)])
        return out

    try:
        from pydoll.commands.network_commands import NetworkCommands

        raw = await tab._execute_command(NetworkCommands.get_cookies())
        cookies.extend(_extract(raw))
    except Exception:
        pass
    try:
        for name in ("get_cookies", "get_all_cookies"):
            fn = getattr(tab, name, None)
            if not fn:
                continue
            raw = await fn()
            if isinstance(raw, list):
                cookies.extend([c for c in raw if isinstance(c, dict)])
            else:
                cookies.extend(_extract(raw))
    except Exception:
        pass
    for c in cookies:
        if str(c.get("name") or "") == "token_v2":
            return str(c.get("value") or "")
    return ""


def _logged_in(url: str, html: str, token: str = "") -> bool:
    if re.search(r"verification code|your login code was incorrect|sign up with your work email", html, re.I):
        return False
    if token:
        return True
    if APP_RE.search(url):
        return True
    if re.search(r"continue with google|work email", html, re.I) and "signup" in url:
        return False
    return False


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
        info = _parse_info(await _js(tab, PAGE_INFO_JS))
        log.info("UI: %s %s", str(info.get("url") or "").split("?")[0], (info.get("body") or "")[:200].replace("\n", " / "))

        filled_e = await _js(tab, FILL_EMAIL_JS.replace("%EMAIL%", json.dumps(email)))
        log.info("Fill email=%s", filled_e)
        clicked = await _js(tab, CLICK_EMAIL_JS)
        if clicked:
            log.info("Click: %s", clicked)
            await _sleep(0.6)
        submitted = await _js(tab, SUBMIT_JS)
        log.info("Submit: %s", submitted)
        await _sleep(3.0)
        html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 1600) : ''") or "")
        log.info("UI after send: %s", html[:220].replace("\n", " / "))
        sent_re = re.compile(
            r"check your (?:email|inbox)|login code|we sent|enter (?:the )?code|verification code|code we sent",
            re.I,
        )
        bad_domain_re = re.compile(
            r"invalid email domain|invalid email|could not reach|couldn't reach|"
            r"unable to (?:send|reach|deliver)|undeliverable|disposable|"
            r"not a valid (?:work )?email|flagged|blocked|"
            r"couldn't find this email",
            re.I,
        )
        if re.search(r"captcha|turnstile|hcaptcha|recaptcha", html, re.I):
            return {"ok": False, "status": "error:need_captcha", "detail": html[:180]}
        if not sent_re.search(html) and bad_domain_re.search(html):
            return {"ok": False, "status": "error:email_domain", "detail": html[:180]}
        if not sent_re.search(html):
            await _sleep(2.5)
            html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 1600) : ''") or "")
            log.info("UI after send (retry): %s", html[:220].replace("\n", " / "))
            if re.search(r"captcha|turnstile|hcaptcha|recaptcha", html, re.I):
                return {"ok": False, "status": "error:need_captcha", "detail": html[:180]}
            if bad_domain_re.search(html):
                return {"ok": False, "status": "error:email_domain", "detail": html[:180]}
            if not sent_re.search(html):
                return {
                    "ok": False,
                    "status": "error:email_not_sent",
                    "detail": html[:180],
                }

        timeout_otp = int(config.get("timeout_otp") or 180)
        log.info("Chờ mail Notion (tmail_wibu, timeout=%ss, có resend)…", timeout_otp)
        proof: dict[str, str] = {}
        t_wait = time.time()
        resent = False
        while time.time() - t_wait < timeout_otp:
            remaining = max(8, int(timeout_otp - (time.time() - t_wait)))
            proof = wait_mail(timeout=min(15, remaining)) or {}
            if proof.get("code") or proof.get("link"):
                break
            if not resent and time.time() - t_wait >= 40:
                rtxt = await _js(tab, RESEND_JS)
                if rtxt:
                    log.info("Resend Notion code: %s", rtxt)
                resent = True
            await _sleep(0.4)
        if proof.get("link"):
            log.info("Mở magic link %s", proof["link"][:90])
            await tab.go_to(proof["link"])
            await _sleep(5)
        elif proof.get("code"):
            n = await _js(tab, FILL_CODE_JS.replace("%CODE%", json.dumps(proof["code"])))
            log.info("Fill login code=%s", n)
            await _js(tab, SUBMIT_JS)
            await _sleep(4)
            html2 = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 800) : ''") or "")
            if re.search(r"incorrect|try again", html2, re.I):
                log.warning("Code sai — chờ mã mới")
                proof2 = wait_mail() or {}
                if proof2.get("code") and proof2.get("code") != proof.get("code"):
                    n = await _js(tab, FILL_CODE_JS.replace("%CODE%", json.dumps(proof2["code"])))
                    log.info("Fill login code retry=%s", n)
                    await _js(tab, SUBMIT_JS)
                    await _sleep(4)
        else:
            return {"ok": False, "status": "error:otp_timeout"}

        for _ in range(5):
            acted = await _js(tab, ONBOARD_JS)
            if acted:
                log.info("Onboard: %s", acted)
                await _sleep(1.3)
            else:
                break

        url = str(await _js(tab, "location.href") or "")
        html = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 1600) : ''") or "")
        sess = _parse_info(await _js(tab, SESSION_JS))
        token = str(sess.get("token_v2") or "")
        if not token:
            token = await _cdp_token_v2(tab)
            if token:
                sess["token_v2"] = token[:12] + "…"
        await dump_network(tab, "after_login")

        if not _logged_in(url, html, token):
            return {
                "ok": False,
                "status": "error:signup_incomplete",
                "url": url,
                "detail": html[:200],
            }

        from notreg.offers import check_subscription, parse_offer

        offer = check_subscription(config, token) if token else parse_offer(html)
        if not offer.get("has_offer") and html:
            page_offer = parse_offer(html)
            if page_offer.get("has_offer"):
                offer = page_offer

        startup = config.get("startup") or {}
        partner = str(startup.get("partner_code") or config.get("partner_code") or "").strip()
        company = str(startup.get("company_website") or startup.get("company_name") or "").strip()
        if config.get("claim_offer") is not False and not partner and not company:
            log.info("Skip startups-apply — không có partner/website (tmail thường Free)")
        elif config.get("claim_offer") is not False:
            apply_url = str(startup.get("apply_url") or "https://www.notion.so/startups-apply")
            log.info("Mở startups apply (1/3/6 tháng Business) %s", apply_url)
            try:
                await tab.go_to(apply_url)
                await _sleep(4)
                if partner:
                    n = await _js(tab, FILL_CODE_JS.replace("%CODE%", json.dumps(partner)))
                    log.info("Fill partner code=%s", n)
                    await _js(tab, SUBMIT_JS)
                    await _sleep(3)
                html2 = str(await _js(tab, "document.body ? document.body.innerText.slice(0, 2500) : ''") or "")
                await dump_network(tab, "startups_apply")
                applied = parse_offer(html2)
                if applied.get("months") or applied.get("has_offer"):
                    offer = {**offer, **applied, "has_offer": True}
                elif re.search(r"thank|submitted|we'll email|we will email|approved", html2, re.I):
                    offer["apply_submitted"] = True
                    offer["summary"] = (offer.get("summary") or "free") + " · form submitted"
            except Exception as e:
                log.warning("startups-apply skip: %s", e)

        return {
            "ok": True,
            "status": "success",
            "url": url,
            "offer": offer,
            "session": {"email": email, "token_v2": (token[:12] + "…") if token else "", "url": url},
        }
    finally:
        await close_browser(browser)
