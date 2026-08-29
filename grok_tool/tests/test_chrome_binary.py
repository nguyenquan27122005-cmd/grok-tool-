"""Tests cho config `chrome_binary` — custom Chromium-compatible binary.

Cho phép chạy reg bằng build stealth khác (VD CloakBrowser) mà không đổi
flow: chỉ thay binary underneath. Thiếu binary → fallback Chrome mặc định,
không crash batch.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grokreg.browser.chrome import build_chrome_options

_CFG = {"fresh_profile_per_account": True, "antiflag": {"browser_preferences": False}}


class ChromeBinaryTest(unittest.TestCase):
    def test_empty_uses_default_chrome(self) -> None:
        o = build_chrome_options(dict(_CFG))
        self.assertFalse(getattr(o, "binary_path", None))

    def test_missing_binary_falls_back(self) -> None:
        cfg = dict(_CFG, chrome_binary=r"C:\nope\missing_chrome.exe")
        o = build_chrome_options(cfg)
        self.assertFalse(getattr(o, "binary_path", None))

    def test_existing_binary_is_used(self) -> None:
        fake_bin = sys.executable  # bất kỳ file tồn tại nào — chỉ test wiring
        cfg = dict(_CFG, chrome_binary=fake_bin)
        o = build_chrome_options(cfg)
        self.assertEqual(str(getattr(o, "binary_path", "")), fake_bin)


if __name__ == "__main__":
    unittest.main()