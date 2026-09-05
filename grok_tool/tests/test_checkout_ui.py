"""Bật/tắt chế độ "Lấy link thanh toán" (OpenArt/SciSpace) phải được wire trong app.js.

Không cần DOM: trích bằng regex — bắt được lỗi ai xóa hàm sync, quên gọi
khi job đổi, hoặc bỏ qua check pool Hotmail ở Start khi job=checkout.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_console" / "static" / "js" / "app.js"


class CheckoutUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js_src = JS.read_text(encoding="utf-8")
        cls.body = cls.js_src.split("function syncCheckoutJobUi", 1)[1].split("\nfunction ", 1)[0]

    def test_sync_fn_defined_and_wired(self) -> None:
        self.assertIn("function syncCheckoutJobUi(root)", self.js_src)
        # 1 định nghĩa + gọi khi job đổi + gọi lúc bind form
        self.assertGreaterEqual(self.js_src.count("syncCheckoutJobUi(root)"), 3)

    def test_checkout_fields_toggle(self) -> None:
        # field chỉ dùng ở chế độ checkout phải nằm trong danh sách bật/tắt
        for key in ("checkout_plans", "checkout_interval", "push_gsheet"):
            self.assertIn(f"'{key}'", self.body)
        # phần reg bị ẩn khi checkout
        for key in ("'mail'", "'count'", "'threads'", "'resume'"):
            self.assertIn(key, self.body)
        self.assertIn("custom_read_mailbox", self.body)

    def test_start_skips_hotmail_pool_in_checkout(self) -> None:
        # checkout login từ ledger, không cần pool — Start không được chặn vì pool trống
        m = re.search(r"else if \(([^\n]*?)isHotmailMail\(state\.form\.mail\)\)", self.js_src)
        self.assertIsNotNone(m, "mất nhánh kiểm tra pool Hotmail trong onStart")
        self.assertIn("checkout", m.group(1))


if __name__ == "__main__":
    unittest.main()
