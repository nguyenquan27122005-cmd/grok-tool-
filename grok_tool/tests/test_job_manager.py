"""Unit tests cho web_console.job_manager — queue, snapshot wrap, redact, persist.

Không spawn subprocess thật: _spawn được mock, plugin registry không đụng tới.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_console.job_manager import (
    Job,
    JobManager,
    _redact_cmd,
    _redact_params,
)


def make_manager(tmp: Path, max_concurrent: int = 1) -> JobManager:
    return JobManager(tmp, max_concurrent=max_concurrent)


class SnapshotWrapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.job = Job(id="t", tool_id="t", params={})

    def test_wrap_past_offset_resends_whole_buffer(self) -> None:
        for i in range(1, 4010):
            self.job.append_log(f"line{i}")
        self.assertEqual(self.job._log_seq, 4009)
        self.assertEqual(len(self.job.logs), 4000)
        # client đứng ở seq 5 — buffer bắt đầu ở seq 9 → gửi lại cả buffer
        snap = self.job.snapshot(log_from=5)
        self.assertEqual(len(snap["logs"]), 4000)
        self.assertTrue(snap["logs"][0].endswith("line10"))

    def test_partial_offset_sends_only_missing(self) -> None:
        for i in range(1, 4010):
            self.job.append_log(f"line{i}")
        snap = self.job.snapshot(log_from=3000)
        self.assertEqual(len(snap["logs"]), 1009)
        self.assertTrue(snap["logs"][0].endswith("line3001"))
        self.assertTrue(snap["logs"][-1].endswith("line4009"))

    def test_up_to_date_returns_empty(self) -> None:
        for i in range(1, 10):
            self.job.append_log(f"L{i}")
        self.assertEqual(self.job.snapshot(log_from=9)["logs"], [])

    def test_fresh_client_gets_tail_300(self) -> None:
        for i in range(1, 4010):
            self.job.append_log(f"line{i}")
        snap = self.job.snapshot()
        self.assertEqual(len(snap["logs"]), 300)
        self.assertTrue(snap["logs"][-1].endswith("line4009"))

    def test_no_wrap_offset(self) -> None:
        for i in range(1, 6):
            self.job.append_log(f"L{i}")
        snap = self.job.snapshot(log_from=2)
        self.assertEqual([l[-2:] for l in snap["logs"]], ["L3", "L4", "L5"])


class RedactTest(unittest.TestCase):
    def test_redact_params(self) -> None:
        p = _redact_params(
            {"email": "a@b.c", "password": "x", "api_token": "y", "count": 3}
        )
        self.assertEqual(
            p, {"email": "a@b.c", "password": "***", "api_token": "***", "count": 3}
        )

    def test_redact_cmd_both_flag_styles(self) -> None:
        c = _redact_cmd(
            ["python", "main.py", "--password", "secret", "--count=5",
             "--api_token=abc", "--email", "a@b.c"]
        )
        self.assertEqual(
            c,
            ["python", "main.py", "--password", "***", "--count=5",
             "--api_token=***", "--email", "a@b.c"],
        )


class QueueTest(unittest.TestCase):
    def test_start_enqueues_when_busy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jm = make_manager(tmp, max_concurrent=1)
            busy = Job(id="busy", tool_id="grok", params={})
            busy.status = "running"
            jm._jobs["busy"] = busy
            queued = Job(id="q1", tool_id="grok", params={})
            queued.status = "queued"
            queued._on_update = jm._publish
            jm._jobs["q1"] = queued
            jm._queue.append("q1")

            spawned: list[str] = []
            with mock.patch.object(jm, "_spawn", side_effect=lambda j, p: spawned.append(j.id)):
                jm._pump()
            # busy chiếm slot → q1 không được spawn
            self.assertEqual(spawned, [])
            self.assertEqual(jm.queue_info(), [{"id": "q1", "tool_id": "grok"}])

            busy.status = "done"
            with mock.patch.object(jm, "_spawn", side_effect=lambda j, p: spawned.append(j.id)):
                jm._pump()
            self.assertEqual(spawned, ["q1"])
            self.assertEqual(jm.queue_info(), [])
            self.assertEqual(jm._jobs["q1"].status, "pending")

    def test_stop_cancels_queued_job(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jm = make_manager(tmp)
            queued = Job(id="q1", tool_id="grok", params={})
            queued.status = "queued"
            jm._jobs["q1"] = queued
            jm._queue.append("q1")
            res = jm.stop("q1")
            self.assertTrue(res["ok"])
            self.assertEqual(queued.status, "stopped")
            self.assertEqual(jm.queue_info(), [])
            # history đã ghi 1 dòng
            lines = (tmp / "data" / "jobs.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["status"], "stopped")


class PersistTest(unittest.TestCase):
    def test_persist_and_load_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jm = make_manager(tmp)
            j = Job(
                id="abc123",
                tool_id="grok",
                params={"count": 3, "password": "x"},
                status="done",
                created_at=1.0,
                started_at=2.0,
                ended_at=3.0,
                exit_code=0,
            )
            jm._persist(j)

            jm2 = make_manager(tmp)
            loaded = jm2.get("abc123")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, "done")
            self.assertEqual(loaded.exit_code, 0)
            # password không bao giờ xuống disk
            self.assertEqual(loaded.params.get("password"), "***")
            self.assertEqual(loaded.params.get("count"), 3)

    def test_interrupted_active_job_marked_stopped_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir(parents=True)
            rec = {
                "id": "dead",
                "tool_id": "grok",
                "params": {},
                "status": "running",
                "created_at": 1.0,
                "started_at": 2.0,
            }
            (tmp / "data" / "jobs.jsonl").write_text(
                json.dumps(rec) + "\n", encoding="utf-8"
            )
            jm = make_manager(tmp)
            self.assertEqual(jm.get("dead").status, "stopped")


class LogFileTest(unittest.TestCase):
    def test_append_log_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "job.log"
            job = Job(id="f1", tool_id="grok", params={})
            job.log_path = p
            job._log_fh = p.open("w", encoding="utf-8")
            try:
                job.append_log("hello")
                job.append_log("world")
            finally:
                job._log_fh.close()
                job._log_fh = None
            content = p.read_text(encoding="utf-8")
            self.assertIn("hello", content)
            self.assertIn("world", content)


class NotifyJobTest(unittest.TestCase):
    def test_notify_on_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            jm = make_manager(Path(td))
            j = Job(id="n1", tool_id="grok", params={}, status="done",
                    started_at=1.0, ended_at=3.0, exit_code=0)
            calls: list[tuple[str, str]] = []

            with mock.patch(
                "web_console.job_manager.notifier.notify",
                side_effect=lambda ev, msg: calls.append((ev, msg)) or True,
            ):
                jm._notify(j)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "job_done")
            self.assertIn("grok", calls[0][1])

            # job chưa kết thúc → không notify
            calls.clear()
            j2 = Job(id="n2", tool_id="grok", params={}, status="running")
            with mock.patch(
                "web_console.job_manager.notifier.notify",
                side_effect=lambda ev, msg: calls.append((ev, msg)) or True,
            ):
                jm._notify(j2)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
