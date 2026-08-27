"""Tests cho /api/jobs handlers (web_console.app) — mock JobManager.

Không spawn subprocess: fake manager trả job với `.snapshot()`, verify wiring
của route (list/current/start/stop và rollback lỗi 400/404).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException

from web_console.app import (
    StartBody,
    StopBody,
    current_job,
    get_job,
    list_jobs,
    start_job,
    stop_job,
)

_MOD = "web_console.app"


class _SnapJob:
    """Job fake tối thiểu — có `.snapshot()` để route dùng."""

    def __init__(self, jid, tool="grok", status="done", params=None):
        self.id = jid
        self.tool_id = tool
        self.status = status
        self.params = params or {}
        self.log_seq = 0

    def snapshot(self, log_from=0):
        return {
            "id": self.id, "tool_id": self.tool_id, "status": self.status,
            "params": self.params, "log_seq": self.log_seq, "logs": [],
            "running": self.status in ("running", "stopping"),
        }


class _FakeManager:
    """Stub đủ method mà route gọi."""

    def __init__(self):
        self.jobs = {}
        self.queue = []
        self.max_concurrent = 1

    def add(self, job):
        self.jobs[job.id] = job

    def list_jobs(self, limit=50):
        return [{"id": j.id} for j in list(self.jobs.values())[:limit]]

    def current(self):
        return next((j for j in self.jobs.values()
                     if j.status in ("pending", "running", "stopping", "queued")), None)

    def queue_info(self):
        return self.queue

    def get(self, job_id):
        return self.jobs.get(job_id)

    def start(self, tool_id, params):
        if tool_id == "bad-tool":
            raise ValueError("tool not found")
        j = _SnapJob(f"job-{tool_id}", tool_id, "done", params=params)
        self.add(j)
        return j

    def stop(self, job_id=None):
        return {"status": "stopped", "stopped": True}


class JobsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeManager()
        patcher = mock.patch(f"{_MOD}.jobs", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake.add(_SnapJob("j1", "grok", "running", {"count": 2}))

    def test_list_jobs_structure(self) -> None:
        out = list_jobs()
        self.assertIn("jobs", out)
        self.assertIn("current", out)
        self.assertIn("queue", out)
        self.assertIn("max_concurrent", out)

    def test_list_jobs_current_snapshot(self) -> None:
        out = list_jobs()
        cur = out["current"]
        self.assertEqual(cur["id"], "j1")
        self.assertTrue(cur["running"])

    def test_current_job_returns_snapshot_with_queue(self) -> None:
        out = current_job()
        self.assertEqual(out["id"], "j1")
        self.assertEqual(out["tool_id"], "grok")
        self.assertEqual(out["log_seq"], 0)
        self.assertEqual(out["queue"], [])

    def test_current_job_idle_when_none(self) -> None:
        self.fake.jobs.clear()
        out = current_job()
        self.assertEqual(out["status"], "idle")
        self.assertFalse(out["running"])

    def test_current_falls_back_to_last_job(self) -> None:
        self.fake.jobs.clear()
        self.fake.add(_SnapJob("zz-last", "grok", "done"))
        # current() = None (không job active) → _last_job trả job phải nhất
        out = current_job()
        self.assertEqual(out["id"], "zz-last")

    def test_get_job_missing_raises_404(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            get_job("nope")
        self.assertEqual(cm.exception.status_code, 404)

    def test_get_job_returns_snapshot(self) -> None:
        out = get_job("j1")
        self.assertEqual(out["id"], "j1")
        self.assertEqual(out["tool_id"], "grok")

    def test_start_job_calls_manager(self) -> None:
        out = start_job(StartBody(tool_id="grok", params={"count": 3}))
        self.assertTrue(out["ok"])
        self.assertEqual(out["job"]["tool_id"], "grok")
        self.assertEqual(out["job"]["params"], {"count": 3})

    def test_start_job_bad_tool_raises_400(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            start_job(StartBody(tool_id="bad-tool", params={}))
        self.assertEqual(cm.exception.status_code, 400)

    def test_stop_job(self) -> None:
        out = stop_job(StopBody(job_id="j1"))
        self.assertTrue(out["stopped"])
        self.assertEqual(out["status"], "stopped")


if __name__ == "__main__":
    unittest.main()