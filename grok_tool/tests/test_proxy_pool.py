"""Unit tests cho web_console.proxy_pool._normalize_one — các định dạng proxy.

Không dùng mạng: chỉ kiểm normalize chuỗi.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_console.proxy_pool import _normalize_one


class NormalizeOneTest(unittest.TestCase):
    def test_host_port(self):
        self.assertEqual(_normalize_one("1.2.3.4:8080"), "http://1.2.3.4:8080")

    def test_user_pass_at_host_port(self):
        self.assertEqual(
            _normalize_one("user:pass@1.2.3.4:8080"),
            "http://user:pass@1.2.3.4:8080",
        )

    def test_ip_port_user_pass(self):
        self.assertEqual(
            _normalize_one("222.255.181.110:35187:r1h4:r1h4"),
            "http://r1h4:r1h4@222.255.181.110:35187",
        )

    def test_ip_port_user_pass_with_noise(self):
        self.assertEqual(
            _normalize_one(" <10.0.0.1:3128:u:p>, "),
            "http://u:p@10.0.0.1:3128",
        )

    def test_full_url_pass_through(self):
        self.assertEqual(
            _normalize_one("http://u:p@1.2.3.4:8080"),
            "http://u:p@1.2.3.4:8080",
        )

    def test_socks5(self):
        self.assertEqual(
            _normalize_one("socks5://1.2.3.4:1080"),
            "socks5://1.2.3.4:1080",
        )

    def test_host_only_default_port(self):
        self.assertEqual(_normalize_one("proxy.example.com"), "http://proxy.example.com:80")

    def test_comment_and_blank(self):
        self.assertEqual(_normalize_one("# ghi chú"), "")
        self.assertEqual(_normalize_one("   "), "")

    def test_bad_port_raises(self):
        with self.assertRaises(ValueError):
            _normalize_one("1.2.3.4:notaport")


if __name__ == "__main__":
    unittest.main()
