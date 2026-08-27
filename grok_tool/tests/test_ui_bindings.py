"""Cross-check UI: mọi `getElementById('...')` trong app.js phải có id khớp.

Chạy nhanh, không cần browser/DOM: trích id bằng regex rồi đối chiếu với
`id="..."` xuất hiện trong app.js (template HTML inline) + index.html.
Bắt được typo / đổi id mà quên cập nhật binding.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_console" / "static" / "js" / "app.js"
HTML = ROOT / "web_console" / "templates" / "index.html"

_BY_ID = re.compile(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)")
_ID_IN_MARKUP = re.compile(r'\bid\s*=\s*["\']([^"\']+)["\']')


class UiBindingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js_src = JS.read_text(encoding="utf-8")
        cls.html_src = HTML.read_text(encoding="utf-8")
        cls.markup_ids = Counter(_ID_IN_MARKUP.findall(cls.js_src))
        cls.markup_ids.update(_ID_IN_MARKUP.findall(cls.html_src))

    def test_app_js_and_index_exist(self) -> None:
        self.assertTrue(JS.exists(), "app.js thiếu")
        self.assertTrue(HTML.exists(), "index.html thiếu")

    def test_all_get_element_by_id_have_markup(self) -> None:
        refs = [m for m in _BY_ID.findall(self.js_src) if not m.startswith("f-")]
        # tên id động build bằng ghép chuỗi → không bắt được; chỉ check literal
        missing = sorted({r for r in refs if self.markup_ids.get(r, 0) == 0 and r not in ("log-box",)})
        self.assertEqual(
            missing, [],
            f"getElementById('{missing[0] if missing else ''}...') "
            "không có id=\"...\" tương ứng trong app.js/index.html",
        )


if __name__ == "__main__":
    unittest.main()