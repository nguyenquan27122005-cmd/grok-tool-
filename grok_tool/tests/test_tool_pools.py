"""Pool Hotmail tách riêng theo tool — sibling không còn đọc/ghi pool Grok.

Chạy nhanh, không đụng data thật: path per-tool + import qua path tùy chọn.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_console.plugins.grok import GrokToolPlugin
from web_console.plugins.openart import OpenartToolPlugin
from web_console.plugins.scispace import ScispaceToolPlugin


class ToolPoolTest(unittest.TestCase):
    def test_sibling_pool_path_is_per_tool(self) -> None:
        ss = ScispaceToolPlugin().hotmail_list_path(ROOT)
        oa = OpenartToolPlugin().hotmail_list_path(ROOT)
        self.assertEqual(ss, ROOT.parent / "Scispace" / "data" / "hotmails.txt")
        self.assertEqual(oa, ROOT.parent / "Openart" / "data" / "hotmails.txt")
        self.assertNotEqual(ss, GrokToolPlugin()._hotmail_path(ROOT))
        self.assertNotEqual(ss, oa)

    def test_grok_pool_accepts_custom_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "pool.txt"
            p.write_text("a@hotmail.com|pw|refresh|cid\n", encoding="utf-8")
            pool = GrokToolPlugin().hotmail_pool(ROOT, path=p)
            self.assertEqual(pool["count"], 1)
            self.assertGreaterEqual(int(pool["slots"]), 1)

    def test_import_writes_custom_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sub" / "pool.txt"
            res = GrokToolPlugin().import_hotmails(ROOT, "a@hotmail.com|pw|r|c", path=p)
            self.assertEqual(res["added"], 1)
            self.assertIn("a@hotmail.com", p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
