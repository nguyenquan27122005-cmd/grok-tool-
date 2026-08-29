"""Smoke test CloakBrowser binary qua pydoll — đúng flow tool (build_chrome_options).

Đọc chrome_binary từ config.json (fallback: cache .cloakbrowser cạnh repo).
Chạy: venv/Scripts/python.exe scripts/smoke_cloakbrowser.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pydoll.browser.chromium import Chrome

from grokreg.browser.chrome import _safe_add_arg, build_chrome_options
from grokreg.core.config import load_config


def _find_binary() -> str:
    cfg = load_config()
    binary = str(cfg.get("chrome_binary") or "").strip()
    if binary and Path(binary).is_file():
        return binary
    cache = Path(os.environ.get("CLOAKBROWSER_CACHE_DIR") or ROOT.parent / ".cloakbrowser")
    if cache.is_dir():
        for child in sorted(cache.glob("chromium-*/chrome.exe"), reverse=True):
            return str(child)
    return ""


async def main() -> int:
    binary = _find_binary()
    print(f"[smoke] binary: {binary or '(KHÔNG TÌM THẤY)'}")
    if not binary:
        print("[smoke] RESULT: FAIL — chưa có binary. Chạy 'python -m cloakbrowser install' "
              "rồi set chrome_binary trong config.json")
        return 1

    cfg = {
        "chrome_binary": binary,
        "fresh_profile_per_account": True,
        "antiflag": {"browser_preferences": False},
        "chrome_user_data_dir": str(ROOT / "chrome_runs" / "smoke_cloak"),
    }
    options = build_chrome_options(cfg)
    options.binary_path = binary
    for arg in ("--headless=new", "--window-size=800,600", "--disable-gpu"):
        _safe_add_arg(options, arg)

    browser = Chrome(options=options)
    tab = await browser.start()
    try:
        await tab.go_to("https://example.com", timeout=30)
        await asyncio.sleep(1)
        title = await tab.title
        ua_res = await tab.execute_script("return navigator.userAgent;")
        ua = ua_res.get("result", {}).get("result", {}).get("value", "?") if isinstance(ua_res, dict) else ua_res
        print(f"[smoke] title: {title!r}")
        print(f"[smoke] user-agent: {ua}")
        ok = bool(title and "Example" in title)
        print(f"[smoke] RESULT: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        await asyncio.shield(getattr(browser, "stop", lambda: asyncio.sleep(0))())


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
