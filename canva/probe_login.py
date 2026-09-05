"""Thử login bằng email + mật khẩu để xác nhận mk hoạt động."""

import asyncio
import json
import sys

sys.path.insert(0, r"D:\grok_tool\canva")
sys.path.insert(0, r"D:\grok_tool\grok_tool")

from canreg.browser import (
    _body,
    _click,
    _click_continue,
    _fill,
    _js,
    _logged_in,
    _sleep,
    _wait_stage,
    open_browser,
)
from canreg.config import load_config
from canreg.redeem import FILL_PROMO_JS


async def probe(email: str, password: str) -> None:
    config = load_config()
    browser, tab = await open_browser(config)
    await tab.go_to("https://www.canva.com/login")
    await _sleep(2.5)
    clicked = await _click(tab, "continue with email", "log in with email")
    if clicked:
        await _wait_stage(tab, not_in=("landing",), seconds=8)
    await _fill(tab, "email", email)
    await _sleep(0.4)
    await _click_continue(tab)
    await _sleep(3.0)
    body = await _body(tab)
    low = body.lower()
    print(f"{email}")
    print("  ô mật khẩu hiện:", "enter password" in low or "password" in low and "forgot password" in low)
    raw = await _js(tab, FILL_PROMO_JS.replace("%VAL%", json.dumps(password)))
    print("  fill mk:", raw)
    await _click_continue(tab)
    await _sleep(4.5)
    url = str(await _js(tab, "location.href") or "")
    body = await _body(tab)
    print("  logged_in:", _logged_in(url, body), "| url:", url[:90])
    errs = [ln.strip() for ln in body.splitlines() if "incorrect" in ln.lower() or "wrong" in ln.lower()]
    print("  lỗi:", errs[:2] or "không có")


if __name__ == "__main__":
    asyncio.run(probe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Canva@2026!Safe"))
