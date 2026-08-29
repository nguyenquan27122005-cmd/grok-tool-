"""Unit tests cho web_console.daemon — single-instance lock + port probe.

Không spawn uvicorn thật: chỉ test helper mà watchdog dựa vào (điểm yếu từng
làm console chết âm thầm khi child "sống mà điếc" sau WinError 10055).
"""

from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_console import daemon


class SingleInstanceLockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(daemon, "LOCK_FILE", Path(self.tmp.name) / "daemon.lock")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_refused_when_other_daemon_alive(self) -> None:
        daemon.LOCK_FILE.write_text("123456", encoding="utf-8")
        with mock.patch.object(daemon, "_pid_alive", return_value=True):
            self.assertFalse(daemon._acquire_single_instance())

    def test_takeover_when_lock_stale(self) -> None:
        daemon.LOCK_FILE.write_text("123456", encoding="utf-8")
        with mock.patch.object(daemon, "_pid_alive", return_value=False):
            self.assertTrue(daemon._acquire_single_instance())

    def test_takeover_when_lock_garbage(self) -> None:
        daemon.LOCK_FILE.write_text("not-a-pid", encoding="utf-8")
        self.assertTrue(daemon._acquire_single_instance())

    def test_lock_file_written(self) -> None:
        self.assertTrue(daemon._acquire_single_instance())
        self.assertEqual(daemon.LOCK_FILE.read_text(encoding="utf-8"), str(daemon.os.getpid()))


class PortProbeTest(unittest.TestCase):
    def test_accepting_on_listening_port(self) -> None:
        srv = socket.socket()
        try:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            self.assertTrue(daemon._port_accepting("127.0.0.1", port, timeout=1))
        finally:
            srv.close()

    def test_not_accepting_on_closed_port(self) -> None:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        finally:
            s.close()
        self.assertFalse(daemon._port_accepting("127.0.0.1", port, timeout=1))


class PidAliveTest(unittest.TestCase):
    def test_own_pid_alive(self) -> None:
        import os

        self.assertTrue(daemon._pid_alive(os.getpid()))

    def test_invalid_pid_dead(self) -> None:
        self.assertFalse(daemon._pid_alive(0))
        self.assertFalse(daemon._pid_alive(-1))


if __name__ == "__main__":
    unittest.main()
