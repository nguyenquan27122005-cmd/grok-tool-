"""Unit tests cho web_console.proxy_pool — normalize + apply/marker + health-check + xoay."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grokreg.core.proxy_rotate import next_proxy
from web_console import proxy_pool
from web_console.proxy_pool import _normalize_one, mask, pick_alive, apply_proxy_to_config


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


class ApplyPoolTest(unittest.TestCase):
    def test_apply_writes_pool_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            p.write_text(json.dumps({"proxy": "", "other": 1}), encoding="utf-8")
            apply_proxy_to_config(
                p, "http://u:p@1.2.3.4:8080", pool=["http://u:p@1.2.3.4:8080", "http://5.6.7.8:3128"]
            )
            d = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(d["proxy"], "http://u:p@1.2.3.4:8080")
            self.assertEqual(len(d["proxy_pool"]), 2)
            self.assertEqual(d["proxy_source"], "pool")
            self.assertEqual(d["other"], 1)  # key khác giữ nguyên

    def test_disable_clears_only_pool_written(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.json"
            apply_proxy_to_config(p, "http://1.2.3.4:8080", pool=["http://1.2.3.4:8080"])
            apply_proxy_to_config(p, "")
            d = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(d["proxy"], "")
            self.assertNotIn("proxy_pool", d)
            self.assertNotIn("proxy_source", d)
            # proxy đi tay → tắt pool KHÔNG được đụng tới
            p2 = Path(td) / "b.json"
            p2.write_text(json.dumps({"proxy": "http://manual:1"}), encoding="utf-8")
            apply_proxy_to_config(p2, "")
            self.assertEqual(json.loads(p2.read_text(encoding="utf-8"))["proxy"], "http://manual:1")

    def test_pick_alive_skips_dead(self) -> None:
        state = {
            "enabled": True,
            "mode": "rotate",
            "proxies": ["http://dead1:1", "http://dead2:2", "http://alive:3"],
            "cursor": 0,
        }
        with mock.patch.object(proxy_pool, "_load", return_value=state), mock.patch.object(
            proxy_pool, "_save", lambda s: None
        ), mock.patch.object(proxy_pool, "_tcp_ok", side_effect=lambda p: "dead" not in p):
            proxy, idx, dead = pick_alive()
            self.assertEqual(proxy, "http://alive:3")
            self.assertEqual(len(dead), 2)
            self.assertEqual(mask(dead[0]), dead[0])  # không chứa user:pass thật
            # cả pool chết → trả rỗng sau max_tries
            with mock.patch.object(proxy_pool, "_tcp_ok", return_value=False):
                proxy, _, dead = pick_alive()
            self.assertEqual(proxy, "")
            self.assertEqual(len(dead), 3)


class RotateTest(unittest.TestCase):
    def test_next_proxy_rotates_and_falls_back(self) -> None:
        cfg = {"proxy_pool": ["http://a:1", "http://b:2", "http://c:3"], "proxy": "http://old:9"}
        got = {next_proxy(cfg) for _ in range(30)}
        self.assertEqual(got, {"http://a:1", "http://b:2", "http://c:3"})
        self.assertEqual(next_proxy({"proxy_pool": [], "proxy": "http://old:9"}), "http://old:9")
        self.assertEqual(next_proxy({"proxy_pool": ["http://only:1"]}), "http://only:1")


if __name__ == "__main__":
    unittest.main()
