"""Đặt mật khẩu cho acc đã reg nhưng bước set-pw bị skip (trang /login/reset
chưa render kịp form). Login lại bằng OTP qua hộp tmail rồi đi đặt mk.

Chạy:  venv python fix_pw.py email1@x.name.ng email2@x.name.ng
"""

import asyncio
import sys
import time

sys.path.insert(0, r"D:\grok_tool\canva")
sys.path.insert(0, r"D:\grok_tool\grok_tool")

from canreg.browser import _set_account_password, open_browser
from canreg.config import load_config
from canreg.mail import wait_canva_mail
from canreg.redeem import Acc, _login_browser
from grokreg.mail.tmail_wibu import TmailWibuProvider


async def main() -> None:
    targets = [a.strip() for a in sys.argv[1:] if "@" in a]
    if not targets:
        print("dùng: python fix_pw.py <email1> <email2> ...")
        return
    config = load_config()
    tmail = TmailWibuProvider(dict(config.get("tmail_wibu") or {}))
    browser, tab = await open_browser(config)
    for email in targets:
        class Sess:
            provider = "tmail_wibu"
            address = email
            refresh_token = ""
            client_id = ""
            extra = {"mailbox": email}

        def wait_mail(_email=email, _sess=Sess):
            return wait_canva_mail(
                _sess(),
                config,
                tmail=tmail,
                timeout=int(config.get("timeout_otp") or 180),
                since=time.time() - 3,
            )

        acc = Acc(email=email, password="Canva@2026!Safe", extra={"mailbox": email})
        st = await _login_browser(tab, acc, config)
        print(f"login {email} → {st}", flush=True)
        if st not in ("ok", "already"):
            continue
        pw = await _set_account_password(tab, email, acc.password, config, wait_mail)
        print(f"setpw {email} → {pw}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
