"""Tests cho /api/solver handlers (web_console.app) — mock solver_manager/notifier.

Chạy cross-platform, không nối tới Camoufox hay process solver thật.
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

from web_console.app import SolverActionBody, solver_action, solver_status

_MOD = "web_console.app"


class _InlineThread:
    def __init__(self, **kw):
        target = kw.get("target")
        args = kw.get("args") or ()
        kwargs = kw.get("kwargs") or {}
        if target:
            target(*args, **kwargs)

    def start(self):
        pass


class SolverStatusTest(unittest.TestCase):
    def test_status_wires_manager_and_monitor(self) -> None:
        with mock.patch(f"{_MOD}.load_config", return_value={}), \
             mock.patch(f"{_MOD}.solver_manager.configure_from_settings") as cfg, \
             mock.patch(f"{_MOD}.solver_manager.get_status",
                        return_value={"online": True, "port": 5072, "pid": 123}), \
             mock.patch(f"{_MOD}.notifier.configured", return_value=True), \
             mock.patch(f"{_MOD}.solver_monitor.interval", 30):
            st = solver_status()
        self.assertTrue(st["online"])
        self.assertEqual(st["port"], 5072)
        self.assertTrue(st["notify_configured"])
        self.assertEqual(st["monitor_interval"], 30)
        cfg.assert_called_once()


class SolverActionTest(unittest.TestCase):
    def _run(self, action):
        return solver_action(SolverActionBody(action=action))

    def test_bad_action_rejected(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            self._run("jump")
        self.assertEqual(cm.exception.status_code, 400)

    def test_start_calls_manager_start(self) -> None:
        with mock.patch(f"{_MOD}.load_config", return_value={"turnstile": {}}), \
             mock.patch(f"{_MOD}.threading.Thread", _InlineThread), \
             mock.patch(f"{_MOD}.solver_manager.start") as start:
            res = self._run("start")
        self.assertTrue(res["ok"])
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs["force"], True)

    def test_stop_calls_manager_stop(self) -> None:
        with mock.patch(f"{_MOD}.threading.Thread", _InlineThread), \
             mock.patch(f"{_MOD}.solver_manager.stop") as stop:
            res = self._run("stop")
        self.assertTrue(res["ok"])
        stop.assert_called_once()

    def test_restart_calls_manager_restart(self) -> None:
        with mock.patch(f"{_MOD}.load_config", return_value={}), \
             mock.patch(f"{_MOD}.threading.Thread", _InlineThread), \
             mock.patch(f"{_MOD}.solver_manager.restart") as restart:
            res = self._run("restart")
        self.assertTrue(res["ok"])
        restart.assert_called_once()


if __name__ == "__main__":
    unittest.main()