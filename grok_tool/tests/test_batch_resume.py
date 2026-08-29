"""Unit test vòng đời resume/checkpoint của engine worker (dùng nfreg làm đại diện).

Không gọi mạng: register_one bị thay bằng fake, BATCH_STATE trỏ vào temp dir.
Kịch bản: batch 3 lượt, chạy 1 lượt rồi gián đoạn (StopRequested) → checkpoint
còn pending=2 → resume=True chạy đúng 2 lượt còn lại và xóa checkpoint.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GROK_ROOT = Path(__file__).resolve().parents[1]
NETFLIX_DIR = GROK_ROOT.parent / "netflix"
for p in (str(GROK_ROOT), str(NETFLIX_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from nfreg import worker as nw
    from nfreg.stop import StopRequested
except ImportError:
    # Repo public chỉ publish grok_tool (gitignore "/*") — CI checkout không có
    # thư mục sibling netflix/. Skip nguyên module; vẫn chạy đầy đủ ở máy local.
    raise unittest.SkipTest("nfreg (thư mục sibling netflix/) không có trong checkout")


def _mk_result(ok: bool, email: str = "a@b.c") -> nw.Result:
    return nw.Result(ok=ok, status="success" if ok else "error:x", email=email,
                     password="p", duration_sec=0.1)


class ResumeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "batch_state.json"
        patcher = mock.patch.object(nw, "BATCH_STATE", self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        # cô lập với STOP file thật của engine (còn sót sau khi user Stop job)
        stop_patch = mock.patch.object(nw, "raise_if_stop", lambda: None)
        stop_patch.start()
        self.addCleanup(stop_patch.stop)
        # không sleep thật giữa các lượt
        self.cfg = {"inter_success_delay_min": 0, "inter_success_delay_max": 0}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_interrupted_batch_leaves_checkpoint(self) -> None:
        calls = {"n": 0}

        def fake_register_one(config):
            calls["n"] += 1
            if calls["n"] == 1:
                return _mk_result(True, "one@x.test")
            raise StopRequested("mang mat")

        with mock.patch.object(nw, "register_one", side_effect=fake_register_one):
            with self.assertRaises(StopRequested):
                nw.run_batch(dict(self.cfg), 3)

        st = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(st["tool"], "netflix")
        self.assertEqual(st["planned"], 3)
        self.assertEqual(st["done"], 1)
        self.assertEqual(st["pending"], 2)
        self.assertEqual(st["ok"], 1)
        self.assertEqual(st["last_email"], "one@x.test")

    def test_resume_runs_only_pending(self) -> None:
        self.state.write_text(
            json.dumps({
                "tool": "netflix", "planned": 5, "done": 3, "ok": 2,
                "pending": 2, "last_email": "old@x.test",
            }),
            encoding="utf-8",
        )
        ran: list[str] = []

        def fake_register_one(config):
            ran.append("x")
            return _mk_result(True, f"new{len(ran)}@x.test")

        with mock.patch.object(nw, "register_one", side_effect=fake_register_one):
            out = nw.run_batch(dict(self.cfg), 99, resume=True)  # count bị ghi đè bởi checkpoint

        self.assertEqual(len(ran), 2, "phải chạy đúng 2 lượt còn nợ, không phải 99")
        self.assertEqual(len(out), 2)
        self.assertTrue(all(r.ok for r in out))
        # batch xong hẳn → checkpoint bị xóa
        self.assertFalse(self.state.exists())

    def test_resume_without_checkpoint_runs_fresh(self) -> None:
        ran = []

        def fake_register_one(config):
            ran.append(1)
            return _mk_result(True)

        with mock.patch.object(nw, "register_one", side_effect=fake_register_one):
            out = nw.run_batch(dict(self.cfg), 2, resume=True)
        self.assertEqual(len(out), 2)  # không có checkpoint → batch mới count=2
        self.assertFalse(self.state.exists())

    def test_until_stop_mode_writes_no_checkpoint(self) -> None:
        ran = []

        def fake_register_one(config):
            ran.append(1)
            if len(ran) >= 2:
                raise StopRequested("user stop")
            return _mk_result(True)

        with mock.patch.object(nw, "register_one", side_effect=fake_register_one):
            with self.assertRaises(StopRequested):
                nw.run_batch(dict(self.cfg), 0)  # count=0 → until_stop
        self.assertFalse(self.state.exists(), "chế độ ∞ không ghi checkpoint")


if __name__ == "__main__":
    unittest.main()
