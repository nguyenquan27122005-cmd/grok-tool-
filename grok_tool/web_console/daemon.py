"""
Persistent web server — stays up, restarts on crash, no .bat needed.

  python -m web_console.daemon
  python -m web_console.daemon --install    # Task Scheduler @ logon
  python -m web_console.daemon --uninstall
  python -m web_console.daemon --status
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "GrokRegWebConsole"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
LOG_DIR = ROOT / "data"
LOG_FILE = LOG_DIR / "web_daemon.log"
LOCK_FILE = LOG_DIR / "web_daemon.lock"


def _py() -> Path:
    if os.name == "nt":
        # prefer pythonw (no console) for background; fall back to python
        w = ROOT / "venv" / "Scripts" / "pythonw.exe"
        p = ROOT / "venv" / "Scripts" / "python.exe"
        return w if w.exists() else p
    return ROOT / "venv" / "bin" / "python"


def _py_console() -> Path:
    if os.name == "nt":
        return ROOT / "venv" / "Scripts" / "python.exe"
    return ROOT / "venv" / "bin" / "python"


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, errors="replace",
        )
        return str(pid) in (r.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_single_instance() -> bool:
    """Chặn 2 daemon chạy trùng cho cùng ROOT (spawn đôi lúc logon gây giành port).

    Lock file ghi PID: daemon khác sống → exit; lock cũ (daemon đã chết) → chiếm quyền.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    my_pid = os.getpid()
    if LOCK_FILE.exists():
        try:
            old = int(LOCK_FILE.read_text(encoding="utf-8", errors="replace").strip() or 0)
        except ValueError:
            old = 0
        if old and old != my_pid and _pid_alive(old):
            return False
    LOCK_FILE.write_text(str(my_pid), encoding="utf-8")
    return True


def _port_accepting(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        proc.terminate()


def run_loop(host: str, port: int) -> None:
    """Restart uvicorn forever until process is killed."""
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ["WEB_HOST"] = host
    os.environ["WEB_PORT"] = str(port)

    py = str(_py())  # pythonw: no console flash on spawn/restart
    backoff = 2
    _log(f"daemon start host={host} port={port} py={py}")

    if not _acquire_single_instance():
        _log(f"another daemon already runs for this ROOT/port {port} — exit")
        return

    while True:
        cmd = [
            py,
            "-m",
            "uvicorn",
            "web_console.app:app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "info",
        ]
        _log("spawning: " + " ".join(cmd))
        proc: subprocess.Popen | None = None
        logf = None
        code = 0
        try:
            # Append server stdout/stderr to daemon log
            logf = open(LOG_FILE, "a", encoding="utf-8")
            logf.write(f"\n--- uvicorn {time.strftime('%H:%M:%S')} ---\n")
            logf.flush()
            hide = {}
            if os.name == "nt":
                from grokreg.core import winhide

                hide = winhide.kwargs(new_group=True)
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=os.environ.copy(),
                stdout=logf,
                stderr=subprocess.STDOUT,
                **hide,
            )

            # Poll thay vì wait() block: child có thể "sống mà điếc" — process
            # còn nhưng listener chết (VD WinError 10055 cạn socket buffer khi
            # reg job spawn Chrome) và KHÔNG BAO GIỜ exit → daemon phải probe
            # port rồi kill + respawn, nếu không console chết âm thầm mãi mãi.
            deaf_since: float | None = None
            code = None
            while True:
                code = proc.poll()
                if code is not None:
                    break
                if _port_accepting(host, port):
                    deaf_since = None
                elif deaf_since is None:
                    deaf_since = time.time()
                elif time.time() - deaf_since >= 45:
                    _log(
                        f"port {port} not accepting for 45s while child alive "
                        f"(pid={proc.pid}) — kill & respawn"
                    )
                    _kill_tree(proc)
                    try:
                        code = proc.wait(timeout=15)
                    except Exception:
                        code = -1
                    break
                time.sleep(5)
            _log(f"uvicorn exit={code}")
        except KeyboardInterrupt:
            _log("daemon stopped (KeyboardInterrupt)")
            if proc is not None and proc.poll() is None:
                try:
                    _kill_tree(proc)
                except Exception:
                    pass
            raise
        except Exception as e:
            _log(f"spawn error: {e}")
            code = 1
            if proc is not None and proc.poll() is None:
                try:
                    _kill_tree(proc)
                except Exception:
                    pass
        finally:
            if logf is not None:
                try:
                    logf.close()
                except Exception:
                    pass

        # brief backoff before restart (crash loop protection)
        _log(f"restart in {backoff}s…")
        time.sleep(backoff)
        backoff = min(30, backoff + 2)


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA") or ""
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_lnk() -> Path:
    return _startup_dir() / "GrokRegWebConsole.lnk"


def install_autostart(host: str, port: int) -> int:
    """Autostart without admin: Startup folder shortcut + start process now."""
    if os.name != "nt":
        print("install only supported on Windows")
        return 1

    py = str(_py_console().resolve())
    pyw = ROOT / "venv" / "Scripts" / "pythonw.exe"
    runner = str(pyw.resolve()) if pyw.exists() else py

    # 1) Startup folder .lnk (no admin, runs every logon)
    try:
        startup = _startup_dir()
        startup.mkdir(parents=True, exist_ok=True)
        lnk = _startup_lnk()
        # PowerShell COM shortcut
        # Escape single quotes for PowerShell
        def _ps(s: str) -> str:
            return s.replace("'", "''")

        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{_ps(str(lnk))}'); "
            f"$s.TargetPath = '{_ps(runner)}'; "
            f"$s.Arguments = '-m web_console.daemon --loop --host {host} --port {port}'; "
            f"$s.WorkingDirectory = '{_ps(str(ROOT))}'; "
            "$s.WindowStyle = 7; "
            "$s.Description = 'Grok Reg Web Console'; "
            "$s.Save(); "
            "Write-Output 'shortcut_ok'"
        )
        from grokreg.core import winhide

        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            **winhide.kwargs(),
        )
        if "shortcut_ok" not in (r.stdout or ""):
            print("shortcut warn:", (r.stdout or "")[:200], (r.stderr or "")[:200])
        else:
            print(f"Startup shortcut: {lnk}")
    except Exception as e:
        print(f"Startup shortcut failed: {e}")

    # 2) Try Task Scheduler (may need admin — optional)
    tr = f'"{runner}" -m web_console.daemon --loop --host {host} --port {port}'
    from grokreg.core import winhide

    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        **winhide.kwargs(),
    )
    r = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/TR",
            tr,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ],
        capture_output=True,
        text=True,
        errors="replace",
        **winhide.kwargs(),
    )
    if r.returncode == 0:
        print(f"Task Scheduler OK: {TASK_NAME}")
        subprocess.run(
            ["schtasks", "/Run", "/TN", TASK_NAME],
            capture_output=True,
            **winhide.kwargs(),
        )
    else:
        print("Task Scheduler skipped (no admin) — using Startup folder only")

    # 3) Start now (hidden)
    start_now(host, port)
    print(f"OK — server should stay up")
    print(f"Open: http://{host}:{port}/")
    print(f"Log:  {LOG_FILE}")
    return 0


def start_now(host: str, port: int) -> None:
    """Spawn background daemon if health check fails."""
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=2) as r:
            if r.status == 200:
                print("Already running")
                return
    except Exception:
        pass

    # Ensure package import works even if launched from another cwd
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    pyw = ROOT / "venv" / "Scripts" / "pythonw.exe"
    py = _py_console()
    # Prefer console python for reliable -m package resolution on Windows
    runner = str(py)
    args = [
        runner,
        "-m",
        "web_console.daemon",
        "--loop",
        "--host",
        host,
        "--port",
        str(port),
    ]
    creation = 0
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        creation = 0x00000008 | 0x00000200 | 0x08000000
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    subprocess.Popen(
        args,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation if os.name == "nt" else 0,
        start_new_session=(os.name != "nt"),
    )
    print("Daemon process started in background")
    time.sleep(2)


def uninstall_autostart() -> int:
    if os.name != "nt":
        print("uninstall only on Windows")
        return 1
    from grokreg.core import winhide

    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        **winhide.kwargs(),
    )
    try:
        lnk = _startup_lnk()
        if lnk.exists():
            lnk.unlink()
            print(f"Removed {lnk}")
    except Exception as e:
        print(f"shortcut remove: {e}")
    print("Autostart removed (kill python process manually if still running)")
    return 0


def status() -> int:
    host = os.environ.get("WEB_HOST") or DEFAULT_HOST
    port = int(os.environ.get("WEB_PORT") or DEFAULT_PORT)
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=3) as r:
            body = r.read().decode("utf-8", errors="replace")
            print("HTTP OK:", body)
    except Exception as e:
        print("HTTP DOWN:", e)

    if os.name == "nt":
        from grokreg.core import winhide

        r = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
            capture_output=True,
            text=True,
            errors="replace",
            **winhide.kwargs(),
        )
        if r.returncode == 0:
            print("--- Task Scheduler ---")
            for line in (r.stdout or "").splitlines():
                if any(
                    k in line
                    for k in (
                        "TaskName",
                        "Status",
                        "Last Run",
                        "Next Run",
                        "Task To Run",
                        "Logon Mode",
                    )
                ):
                    print(line)
        else:
            print(f"Task '{TASK_NAME}' not installed (run --install)")
    print(f"Log file: {LOG_FILE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Grok Reg web daemon")
    ap.add_argument("--host", default=os.environ.get("WEB_HOST") or DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=int(os.environ.get("WEB_PORT") or DEFAULT_PORT))
    ap.add_argument("--loop", action="store_true", help="Run forever (restart on crash)")
    ap.add_argument("--install", action="store_true", help="Install Windows autostart task")
    ap.add_argument("--uninstall", action="store_true", help="Remove autostart task")
    ap.add_argument("--status", action="store_true", help="Check server + task status")
    ap.add_argument("--start", action="store_true", help="Start background daemon once")
    args = ap.parse_args(argv)

    if args.install:
        return install_autostart(args.host, args.port)
    if args.uninstall:
        return uninstall_autostart()
    if args.status:
        return status()
    if args.start:
        start_now(args.host, args.port)
        return status()

    # default: loop (foreground — used by autostart shortcut)
    try:
        run_loop(args.host, args.port)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
