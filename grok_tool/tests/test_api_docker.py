"""Tests cho /api/docker handlers (web_console.app) — không cần Docker/server thật.

Chạy cross-platform: mock subprocess/shutil để route chạy deterministic,
không spawn Docker hay mở thư mục nào.
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

from web_console.app import DockerActionBody, docker_action, docker_status

_MOD = "web_console.app"


class _R:
    """Fake return của subprocess.run."""

    def __init__(self, rc=0, out=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


class _InlineThread:
    """Thread fake — chạy target ngay để `docker_action` hoàn tất (channel sync)."""

    def __init__(self, **kw):
        target = kw.get("target")
        args = kw.get("args") or ()
        kwargs = kw.get("kwargs") or {}
        if target:
            target(*args, **kwargs)

    def start(self):
        pass


class DockerStatusTest(unittest.TestCase):
    def test_not_installed_returns_fast(self) -> None:
        with mock.patch(f"{_MOD}.shutil.which", return_value=None):
            st = docker_status()
        self.assertFalse(st["installed"])
        self.assertEqual(st["containers"], [])
        self.assertIsInstance(st, dict)

    def test_installed_parses_ps(self) -> None:
        fake_ps = (
            "sub2api\tweishaw/sub2api:1\tUp 2 days (healthy)\trunning\n"
            "sub2api-redis\tredis:8-alpine\tUp 2 days (healthy)\trunning\n"
        )

        def fake_run(cmd, **kw):
            if cmd and cmd[0] == "docker" and cmd[1] == "--version":
                return _R(0, "Docker version 29.7.2, build a7dcaa6")
            return _R(0, fake_ps)

        with mock.patch(f"{_MOD}.shutil.which", return_value="docker"), \
             mock.patch(f"{_MOD}.subprocess.run", side_effect=fake_run), \
             mock.patch.object(Path, "exists", return_value=True):
            st = docker_status()

        self.assertTrue(st["installed"])
        self.assertTrue(st["daemon_running"])
        self.assertTrue(st["desktop_found"])
        self.assertIn("29.7.2", st["version"])
        self.assertEqual(len(st["containers"]), 2)
        self.assertEqual(st["containers"][0]["name"], "sub2api")
        self.assertEqual(st["containers"][0]["state"], "running")

    def test_daemon_off_when_ps_fails(self) -> None:
        def fake_run(cmd, **kw):
            if cmd and cmd[1] == "--version":
                return _R(0, "Docker version x")
            return _R(1, "")

        with mock.patch(f"{_MOD}.shutil.which", return_value="docker"), \
             mock.patch(f"{_MOD}.subprocess.run", side_effect=fake_run):
            st = docker_status()
        self.assertFalse(st["daemon_running"])
        self.assertEqual(st["containers"], [])


class DockerActionTest(unittest.TestCase):
    def _run(self, action, name=None):
        return docker_action(DockerActionBody(action=action, name=name))

    def test_bad_action_rejected(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            self._run("reboot")
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("start_daemon", cm.exception.detail)

    def test_container_action_requires_name(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            self._run("restart")
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("tên container", cm.exception.detail)

    def test_start_daemon_on_win_launches_desktop(self) -> None:
        launched: list[str] = []

        def fake_popen(cmd, **kw):
            launched.append(str(cmd[0]))
            return mock.MagicMock()

        with mock.patch(f"{_MOD}.os.name", "nt"), \
             mock.patch.object(Path, "exists", return_value=True), \
             mock.patch(f"{_MOD}.subprocess.Popen", side_effect=fake_popen), \
             mock.patch(f"{_MOD}.threading.Thread", _InlineThread):
            res = self._run("start_daemon")
        self.assertTrue(res["ok"])
        self.assertTrue(launched and launched[0].endswith(".exe"),
                        f"expect Docker Desktop.exe path, got {launched}")

    def test_start_daemon_on_linux_uses_systemctl(self) -> None:
        sub_calls: list[list[str]] = []

        def fake_run(cmd, **kw):
            sub_calls.append(list(cmd))
            return _R(0)

        with mock.patch(f"{_MOD}.os.name", "posix"), \
             mock.patch(f"{_MOD}.Path", mock.MagicMock(spec=Path)), \
             mock.patch(f"{_MOD}.subprocess.run", side_effect=fake_run), \
             mock.patch(f"{_MOD}.threading.Thread", _InlineThread):
            res = self._run("start_daemon")
        self.assertTrue(res["ok"])
        self.assertEqual(sub_calls, [["systemctl", "start", "docker"]])

    def test_restart_container_runs_docker(self) -> None:
        sub_calls: list[list[str]] = []

        def fake_run(cmd, **kw):
            sub_calls.append(list(cmd))
            return _R(0)

        with mock.patch(f"{_MOD}.subprocess.run", side_effect=fake_run), \
             mock.patch(f"{_MOD}.threading.Thread", _InlineThread), \
             mock.patch.object(Path, "exists", return_value=True):
            res = self._run("restart", "sub2api")
        self.assertTrue(res["ok"])
        self.assertEqual(sub_calls, [["docker", "restart", "sub2api"]])


if __name__ == "__main__":
    unittest.main()