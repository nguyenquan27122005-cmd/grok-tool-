"""Unit tests cho web_console.notifier — config resolution + dispatch (no network)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_console import notifier


def _isolate_settings(monkeypatch: mock._patch):
    """Ép load_config trả dict rỗng để test chỉ phụ thuộc env vars."""
    return mock.patch(
        "grokreg.core.config.load_config", return_value={}
    )


class SettingsTest(unittest.TestCase):
    def test_no_config_means_not_configured(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "NOTIFY_WEBHOOK_URL": "",
        }
        with mock.patch.dict("os.environ", env, clear=False), \
                mock.patch("grokreg.core.config.load_config", return_value={}):
            # xóa hoàn toàn nếu có sẵn trong môi trường
            import os
            for k in list(env):
                os.environ.pop(k, None)
            self.assertFalse(notifier.configured())
            self.assertFalse(notifier.notify("job_done", "x"))

    def test_env_vars_configure_telegram(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"},
        ), mock.patch("grokreg.core.config.load_config", return_value={}):
            s = notifier._settings()
            self.assertEqual(s["tg_token"], "123:abc")
            self.assertEqual(s["tg_chat"], "42")
            self.assertTrue(notifier.configured())

    def test_config_json_wins_then_env_fills_gap(self) -> None:
        cfg = {"notify": {"webhook_url": "https://example.com/hook"}}
        with mock.patch.dict(
            "os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
        ), mock.patch("grokreg.core.config.load_config", return_value=cfg):
            s = notifier._settings()
            self.assertEqual(s["webhook"], "https://example.com/hook")
            self.assertEqual(s["tg_token"], "t")  # env lấp chỗ trống


class DispatchTest(unittest.TestCase):
    def test_notify_dispatches_when_configured(self) -> None:
        sent: list[tuple[dict, str, str]] = []

        def fake_send(s, event, message):
            sent.append((s, event, message))

        with mock.patch.dict(
            "os.environ",
            {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"},
        ), mock.patch(
            "grokreg.core.config.load_config", return_value={}
        ), mock.patch.object(notifier, "_send", side_effect=fake_send):
            ok = notifier.notify("job_done", "done msg")
            self.assertTrue(ok)
            # thread daemon chạy nhanh — chờ tới 2s
            for _ in range(40):
                if sent:
                    break
                time.sleep(0.05)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][1], "job_done")
            self.assertEqual(sent[0][2], "done msg")


if __name__ == "__main__":
    unittest.main()
