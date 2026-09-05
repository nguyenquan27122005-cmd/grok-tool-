"""GPM-Login local API (D:\\gpm). Keep GPMLogin.exe running."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from gsparkreg.log import log

DEFAULT_API = "http://127.0.0.1:19995"
PROFILE_DB = Path(r"D:\gpm\gpm profile\profile_data.db")
PORT_FILE = Path(r"D:\gpm\api_port.dat")
GPM_HOME = Path(r"D:\gpm")

# Monitor crack (gpm.ps1) do tool spawn — giữ handle để không nhân bản khi
# reg nhiều acc liên tiếp. Monitor mở tay bằng LaunchGPM.bat phát hiện không
# được nên có thể chạy 2 instance; click dialog của nó idempotent nên vô hại.
_MONITOR_PROC: list = []
_MONITOR_PID_FILE = GPM_HOME / ".gpm_monitor.pid"


def _monitor_alive() -> bool:
    """Có monitor (của tool này hay tool khác ghi lại) đang sống không."""
    try:
        pid = int(_MONITOR_PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
            capture_output=True, text=True, timeout=15,
        ).stdout or ""
        return "POWERSHELL" in out.upper()
    except Exception:
        return False


def api_base(config: dict[str, Any] | None = None) -> str:
    cfg = config or {}
    url = str(cfg.get("gpm_api") or "").strip().rstrip("/")
    if url:
        return url
    if PORT_FILE.exists():
        try:
            port = PORT_FILE.read_text(encoding="utf-8", errors="replace").strip()
            if port.isdigit():
                return f"http://127.0.0.1:{port}"
        except Exception:
            pass
    return DEFAULT_API


def _alive(base: str, timeout: float = 3.0) -> bool:
    """API đang phục vụ không — nhận response nào (kể cả 4xx/5xx) là sống,
    chỉ connection-refused/timeout mới tính là chưa chạy."""
    try:
        requests.get(f"{base}/v2/profiles", params={"page": 1, "per_page": 1}, timeout=timeout)
        return True
    except requests.RequestException:
        return False


def _spawn_monitor() -> bool:
    """Bật monitor gpm.ps1 (ẩn) nếu chưa có bản nào do tool spawn còn sống.

    Điểm mấu chốt: monitor phải READY TRƯỚC khi mở GPMLogin — LaunchGPM.bat
    chỉ đợi 5s là thiếu, monitor lỡ dialog "Enter license" thì GPM chạy thiếu
    license, báo LICENSE_NOT_FOUND rồi tự thoát.
    """
    if _MONITOR_PROC and _MONITOR_PROC[0].poll() is None:
        return True
    if _monitor_alive():
        return True
    ps1 = GPM_HOME / "gpm.ps1"
    if not ps1.exists():
        log.warning("Không thấy %s — không ai xử lý dialog license cho GPM.", ps1)
        return False
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            cwd=str(GPM_HOME),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _MONITOR_PROC[:] = [proc]
        try:
            _MONITOR_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        except Exception:  # noqa: BLE001 — không ghi được pid thì lần sau spawn lại, vô hại
            pass
        return True
    except OSError as e:
        log.warning("Không bật được monitor gpm.ps1: %s", e)
        return False


def _launch_app() -> bool:
    exe = GPM_HOME / "GPMLogin" / "GPMLogin.exe"
    try:
        if exe.exists():
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
            return True
        bat = GPM_HOME / "LaunchGPM.bat"
        if bat.exists():
            subprocess.Popen(
                ["cmd", "/c", str(bat)],
                cwd=str(GPM_HOME),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        log.warning("Không tìm thấy GPMLogin.exe hay LaunchGPM.bat trong %s", GPM_HOME)
        return False
    except OSError as e:
        log.warning("Không mở được GPMLogin: %s", e)
        return False


def ensure_gpm_running(config: dict[str, Any] | None = None, *, wait_seconds: float = 120.0) -> bool:
    """GPM chưa chạy thì TỰ BẬT đúng cách: dọn zombie → monitor crack → đợi
    monitor sẵn sàng 10s → mở GPMLogin → poll API, phải sống ổn định ~10s mới
    tính xong (lên rồi chết ngay là dấu hiệu license hỏng → thử lại ≤2 lần).

    Trả True nếu API sẵn sàng; False là đã cố mà không lên (caller báo lỗi sạch).
    """
    base = api_base(config)
    if _alive(base):
        return True
    host = urlparse(base).hostname or ""
    if host != "localhost" and not host.startswith("127."):
        log.warning("GPM API %s không phản hồi (máy khác — không tự bật được).", base)
        return False

    started = time.monotonic()
    deadline = started + wait_seconds
    log.info("[gpm] GPM chưa chạy — tự bật (đợi tối đa %ds) …", int(wait_seconds))

    # Dọn GPM zombie chết vì license — trùng bước đầu của LaunchGPM.bat.
    try:
        subprocess.run(["taskkill", "/f", "/im", "GPMLogin.exe"], capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001 — chưa có process thì thôi
        pass
    time.sleep(1)

    if not _spawn_monitor():
        return False
    time.sleep(10)  # monitor cần thời gian init (Add-Type + quét core + WMI)

    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if not _launch_app():
            return False
        log.info("[gpm] Đã mở GPMLogin (lần %d) — đợi API …", attempt)
        stable_since: float | None = None
        while time.monotonic() < deadline:
            time.sleep(1.5)
            if _alive(base):
                if stable_since is None:
                    stable_since = time.monotonic()
                    log.info("[gpm] API phản hồi sau ~%.0fs — xác nhận ổn định …", stable_since - started)
                elif time.monotonic() - stable_since >= 10:
                    return True
                continue
            if stable_since is not None:
                log.warning("[gpm] GPM tắt ngay sau khi lên — thử mở lại …")
                break
    log.warning("[gpm] Không bật được GPM sau %ds — mở tay D:\\gpm\\LaunchGPM.bat rồi chạy lại.", int(wait_seconds))
    return False


def _get(base: str, path: str, params: dict[str, Any] | None = None, timeout: float = 60) -> Any:
    q = f"?{urlencode({k: v for k, v in (params or {}).items() if v not in (None, '')})}"
    url = f"{base}{path}{q if params else ''}"
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        raise RuntimeError(
            f"GPM API mất kết nối giữa chừng ({base}) — chạy D:\\gpm\\LaunchGPM.bat rồi thử lại. ({e})"
        ) from e
    text = (r.text or "").strip()
    if r.status_code >= 400:
        raise RuntimeError(f"GPM {path} HTTP {r.status_code}: {text[:240]}")
    if text.upper() == "OK":
        return {"ok": True}
    try:
        return json.loads(text)
    except Exception:
        return text


def list_profiles_db() -> list[dict[str, str]]:
    if not PROFILE_DB.exists():
        return []
    con = sqlite3.connect(f"file:{PROFILE_DB}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT Id, Name, ProfilePath FROM Profiles").fetchall()
    finally:
        con.close()
    return [{"id": str(a), "name": str(b), "path": str(c)} for a, b, c in rows]


def list_profiles(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    base = api_base(config)
    try:
        data = _get(base, "/v2/profiles", {"page": 1, "per_page": 1000}, timeout=8)
    except RuntimeError:
        return list_profiles_db()
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for k in ("data", "profiles", "items"):
            v = data.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return list_profiles_db()


def resolve_profile_id(config: dict[str, Any]) -> str:
    want = str(config.get("gpm_profile") or config.get("gpm_profile_id") or "").strip()
    profiles = list_profiles(config)
    if not profiles:
        raise RuntimeError("GPM không có profile — tạo profile trên GPM-Login trước")
    if not want:
        return str(profiles[0].get("id") or "")
    for p in profiles:
        pid = str(p.get("id") or "")
        name = str(p.get("name") or "")
        if want.lower() in (pid.lower(), name.lower()) or want == pid:
            return pid
    raise RuntimeError(f"Không thấy profile GPM {want!r}. Có: " + ", ".join(
        f"{p.get('name')} ({p.get('id')})" for p in profiles
    ))


def start_profile(config: dict[str, Any]) -> dict[str, Any]:
    base = api_base(config)
    if not ensure_gpm_running(config):
        raise RuntimeError(
            f"GPM không bật được (API {base}) — mở D:\\gpm\\LaunchGPM.bat rồi chạy lại."
        )
    pid = resolve_profile_id(config)
    log.info("GPM start profile=%s api=%s", pid, base)
    data = _get(base, "/v2/start", {"profile_id": pid}, timeout=90)
    if not isinstance(data, dict) or not data.get("status"):
        raise RuntimeError(f"GPM start fail: {data}")
    addr = str(data.get("selenium_remote_debug_address") or "").strip()
    if not addr:
        raise RuntimeError(f"GPM start không trả debug address: {data}")
    log.info("GPM CDP %s", addr)
    data["profile_id"] = data.get("profile_id") or pid
    data["debug_address"] = addr
    return data


def stop_profile(config: dict[str, Any], profile_id: str) -> None:
    base = api_base(config)
    try:
        _get(base, "/v2/stop", {"profile_id": profile_id}, timeout=30)
        log.info("GPM stop %s", profile_id)
    except Exception as e:
        log.warning("GPM stop: %s", e)
