"""Bắt gói POST /_ajax/signup THẬT từ Chrome (hook fetch/XHR) để diff với
protocol.py — chẩn đoán HTTP reg Canva bị 400 vì thiếu field hay captcha.

Chạy:  venv python capture_signup.py
Kết quả: data/signup_capture.json
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canreg.browser import (
    _body,
    _click,
    _click_continue,
    _fill,
    _js,
    _sleep,
    _wait_cf,
    _wait_stage,
    close_browser,
    open_browser,
)
from canreg.config import load_config
from canreg.mail import acquire_email, wait_canva_mail

HOOK_JS = r"""
(() => {
  if (window.__hooked) return "already";
  window.__hooked = 1;
  window.__caps = [];
  const rec = (url, body, headers) => {
    try {
      if (String(url).includes("/_ajax/")) {
        window.__caps.push({
          url: String(url),
          body: body == null ? null : String(body),
          headers: headers && headers instanceof Headers ? Object.fromEntries(headers.entries()) : (headers || {}),
        });
      }
    } catch (e) {}
  };
  const of = window.fetch;
  window.fetch = function (...args) {
    try {
      const [req, init] = args;
      const url = typeof req === "string" ? req : (req && req.url) || "";
      let body = init && init.body != null ? init.body : (req && req.body) || null;
      let headers = (init && init.headers) || (req && req.headers) || {};
      rec(url, body, headers);
    } catch (e) {}
    return of.apply(this, args);
  };
  const oo = XMLHttpRequest.prototype.open;
  const os = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__u = u; return oo.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (b) {
    try { rec(this.__u, b, null); } catch (e) {}
    return os.apply(this, arguments);
  };
  return "hooked";
})()
"""


async def main() -> int:
    config = load_config()
    config["email_provider"] = "tmail_wibu"
    session, hotmail, mail_api, azpop, tmail, mailtm, guerrilla = acquire_email(config)
    email = session.address
    print("email:", email, flush=True)

    def wait_mail():
        return wait_canva_mail(
            session, config, mail_api=mail_api, hotmail=hotmail, azpop=azpop,
            tmail=tmail, mailtm=mailtm, guerrilla=guerrilla, timeout=90,
        )

    browser, tab = await open_browser(config)
    try:
        await tab.go_to("https://www.canva.com/signup/")
        await _sleep(1.5)
        await _wait_cf(tab)
        print("hook:", await _js(tab, HOOK_JS), flush=True)
        clicked = await _click(tab, "continue with email", "sign up with email")
        if clicked:
            await _wait_stage(tab, not_in=("landing",), seconds=8)
        await _fill(tab, "email", email)
        await _sleep(0.4)
        await _click_continue(tab)
        st = await _wait_stage(tab, not_in=("email", "landing"), seconds=12)
        print("stage sau email:", st, flush=True)
        body = await _body(tab)
        if "name" in (body or "").lower()[:400].lower() or st == "name":
            await _fill(tab, "name", "Test Capture")
            await _sleep(0.4)
            await _click_continue(tab)
            await _wait_stage(tab, not_in=("name",), seconds=12)
        # đợi POST signup kịp fire
        for _ in range(10):
            await _sleep(1.0)
            n = await _js(tab, "(window.__caps || []).length")
            try:
                n = int(n or 0)
            except (TypeError, ValueError):
                n = 0
            if n >= 1:
                break
        # điền OTP nếu có để bắt cả gói verify
        proof = wait_mail() or {}
        code = str(proof.get("code") or "")
        print("otp:", code or "không có", flush=True)
        if code:
            from canreg.browser import _fill_otp

            await _fill_otp(tab, code)
            await _sleep(3.0)
        caps = await _js(tab, "JSON.stringify(window.__caps || [])")
        data = json.loads(caps or "[]")
        out = ROOT / "data" / "signup_capture.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"captured {len(data)} requests → {out}", flush=True)
        for c in data:
            print("-", c.get("url"), "| body_len:", len(str(c.get("body") or "")), flush=True)
        return 0
    finally:
        await close_browser(browser)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
