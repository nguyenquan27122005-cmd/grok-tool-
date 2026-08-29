"""Test ERR_CONNECTION_RESET có phải do ECH (Encrypted Client Hello) không.

Launch Chrome headless vào domain bị RST, với/không --disable-features=EncryptedClientHello.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pydoll.browser.chromium import Chrome

URLS = ["https://auth.heygen.com/signup", "https://www.netflix.com/signup", "https://claude.ai/login"]


async def try_nav(args: list[str]) -> None:
    label = " + ".join(a.split("=", 1)[-1] for a in args) or "default"
    for url in URLS:
        options = Chrome.options_manager if False else None
        from pydoll.browser.options import ChromiumOptions

        opts = ChromiumOptions()
        for a in ("--headless=new", "--window-size=800,600", *args):
            try:
                opts.add_argument(a)
            except Exception:
                pass
        browser = Chrome(options=opts)
        tab = await browser.start()
        try:
            await tab.go_to(url, timeout=25)
            title = await tab.title
            print(f"[{label}] {url} → OK title={title!r}")
        except Exception as e:
            print(f"[{label}] {url} → FAIL {type(e).__name__}: {str(e)[:80]}")
        finally:
            try:
                await browser.stop()
            except Exception:
                pass
        await asyncio.sleep(1)


async def main() -> int:
    await try_nav([])
    await try_nav(["--disable-features=EncryptedClientHello"])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
