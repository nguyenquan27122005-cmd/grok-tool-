"""
Web control plane — multi-tool registration console.
Run:  python -m web_console.app
   or CHAY_WEB.bat
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_console import __version__, notifier
from web_console import backup as backup_mod
from web_console import dashboard as dashboard_stats_mod
from web_console import health_check as health_check_mod
from web_console import log_rotation as log_rotation_mod
from web_console.job_manager import JobManager
from web_console.plugins import all_plugins, get_plugin
from web_console.solver_monitor import monitor as solver_monitor
from services import solver_manager
from grokreg.core.config import load_config

logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
TEMPLATES = Path(__file__).resolve().parent / "templates"

@asynccontextmanager
async def lifespan(_: FastAPI):
    solver_monitor.start()
    # dọn data/ cũ ngay khi boot rồi lặp theo lịch (mặc định 6h/lần)
    try:
        log_rotation_mod.RotationLoop(ROOT).start()
    except Exception:
        logger.exception("[boot] rotation loop failed")
    # health-check acc Sub2API nền (interval từ config: health_check.interval_hours)
    try:
        health_check_mod.HealthCheckLoop(ROOT).start()
    except Exception:
        logger.exception("[boot] health check loop failed")
    # auto-backup data/ mỗi ngày (config.json, accounts.txt, hotmails.txt…)
    try:
        backup_mod.BackupLoop(ROOT).start()
    except Exception:
        logger.exception("[boot] backup loop failed")
    yield


app = FastAPI(title="Draco Reg — Control Plane", version=__version__, lifespan=lifespan)


def _max_concurrent_from_env() -> int:
    try:
        return max(1, int(os.environ.get("GROK_WEB_MAX_CONCURRENT", "1")))
    except ValueError:
        return 1


jobs = JobManager(ROOT, max_concurrent=_max_concurrent_from_env())

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


class StartBody(BaseModel):
    tool_id: str = "grok"
    params: dict[str, Any] = Field(default_factory=dict)


class StopBody(BaseModel):
    job_id: Optional[str] = None


class HotmailImportBody(BaseModel):
    text: str = ""
    mode: str = "append"  # append | replace


class ProxyBody(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None  # fixed | rotate
    proxies_text: Optional[str] = None  # mỗi dòng 1 proxy; rỗng + enabled=False = tắt


@app.get("/api/proxies")
def proxies_get():
    from web_console import proxy_pool

    st = proxy_pool.get_state()
    return {
        "enabled": st["enabled"],
        "mode": st["mode"],
        "proxies": st["proxies"],
        "count": len(st["proxies"]),
        "next": proxy_pool.mask(st["proxies"][0] if st["proxies"] else ""),
    }


@app.post("/api/proxies")
def proxies_save(body: ProxyBody):
    from web_console import proxy_pool

    if body.mode is not None and body.mode not in ("fixed", "rotate"):
        raise HTTPException(400, "mode phải là 'fixed' hoặc 'rotate'")
    if body.proxies_text is not None:
        bad = proxy_pool.validate_lines(body.proxies_text)
        if bad:
            raise HTTPException(400, "Dòng proxy sai cú pháp — " + "; ".join(bad[:5]))
    st = proxy_pool.save_state(
        enabled=body.enabled,
        mode=body.mode,
        proxies_text=body.proxies_text,
    )
    if body.enabled and not st["proxies"]:
        raise HTTPException(400, "Pool proxy trống — nhập ít nhất 1 proxy trước khi bật")
    # GPT-TOOL :8083 không chạy qua plugin (tile nhảy web riêng) → đồng bộ
    # pool + công tắc sang service đó. Best-effort, không chặn lưu.
    sync_note = proxy_pool.sync_gpttool()
    return {"ok": True, "enabled": st["enabled"], "mode": st["mode"],
            "count": len(st["proxies"]), "gpt_tool": sync_note}


class SolverActionBody(BaseModel):
    action: str = "restart"  # start | stop | restart


BRAND_ICON_V = "1.51"


def resolve_brand_icon(tool_id: str, explicit: str = "") -> str:
    """Official publisher icon. Drop brands/{id}.svg|png|webp — future tools inherit."""
    if explicit:
        src = str(explicit)
        return src if "?" in src else f"{src}?v={BRAND_ICON_V}"
    brands = STATIC / "img" / "brands"
    for ext in (".svg", ".png", ".webp"):
        if (brands / f"{tool_id}{ext}").is_file():
            return f"/static/img/brands/{tool_id}{ext}?v={BRAND_ICON_V}"
    return ""


def _tool_public(p) -> dict[str, Any]:
    m = p.meta
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description,
        "icon": m.icon,
        "brand_icon": resolve_brand_icon(m.id, getattr(m, "brand_icon", "") or ""),
        "external_url": getattr(p, "external_url", ""),
        "status": m.status,
        "color": m.color,
        "fields": [
            {
                "key": f.key,
                "label": f.label,
                "type": f.type,
                "default": f.default,
                "hint": f.hint,
                "min": f.min,
                "max": f.max,
                "options": [
                    {"value": o.value, "label": o.label, "hint": o.hint}
                    for o in (f.options or [])
                ],
            }
            for f in (m.fields or [])
        ],
    }


@app.get("/", response_class=HTMLResponse)
def index():
    html = TEMPLATES / "index.html"
    if not html.exists():
        return HTMLResponse("<h1>Missing templates/index.html</h1>", status_code=500)
    return HTMLResponse(html.read_text(encoding="utf-8"))


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "root": str(ROOT)}


@app.get("/api/tools")
def list_tools():
    return {"tools": [_tool_public(p) for p in all_plugins().values()]}


@app.get("/api/tools/{tool_id}")
def tool_detail(tool_id: str):
    try:
        p = get_plugin(tool_id)
    except KeyError:
        raise HTTPException(404, "tool not found")
    return _tool_public(p)


@app.get("/api/tools/{tool_id}/stats")
def tool_stats(tool_id: str):
    try:
        p = get_plugin(tool_id)
    except KeyError:
        raise HTTPException(404, "tool not found")
    return p.stats(ROOT)


@app.get("/api/tools/{tool_id}/results")
def tool_results(tool_id: str, limit: int = Query(100, ge=1, le=2000)):
    try:
        p = get_plugin(tool_id)
    except KeyError:
        raise HTTPException(404, "tool not found")
    return {"results": p.parse_results(ROOT, limit=limit)}


@app.get("/api/tools/{tool_id}/hotmails")
def tool_hotmails(tool_id: str):
    try:
        p = get_plugin(tool_id)
    except KeyError:
        raise HTTPException(404, "tool not found")
    fn = getattr(p, "hotmail_pool", None)
    if not callable(fn):
        raise HTTPException(404, "tool không hỗ trợ Hotmail pool")
    return fn(ROOT)


@app.post("/api/tools/{tool_id}/hotmails")
def tool_hotmails_import(tool_id: str, body: HotmailImportBody):
    try:
        p = get_plugin(tool_id)
    except KeyError:
        raise HTTPException(404, "tool not found")
    fn = getattr(p, "import_hotmails", None)
    if not callable(fn):
        raise HTTPException(404, "tool không hỗ trợ nhập Hotmail")
    try:
        return fn(ROOT, body.text or "", body.mode or "append")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e


def _last_job():
    listed = jobs.list_jobs(1)
    if listed:
        return jobs.get(listed[0]["id"])
    return None


@app.get("/api/jobs")
def list_jobs():
    return {
        "jobs": jobs.list_jobs(),
        "current": (jobs.current().snapshot() if jobs.current() else None),
        "queue": jobs.queue_info(),
        "max_concurrent": jobs.max_concurrent,
    }


@app.get("/api/jobs/current")
def current_job(log_from: int = 0):
    j = jobs.current() or _last_job()
    if not j:
        return {
            "status": "idle",
            "logs": [],
            "running": False,
            "queue": jobs.queue_info(),
        }
    snap = j.snapshot(log_from=log_from)
    snap["queue"] = jobs.queue_info()
    return snap


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, log_from: int = 0):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j.snapshot(log_from=log_from)


@app.post("/api/jobs/start")
def start_job(body: StartBody):
    try:
        job = jobs.start(body.tool_id, body.params)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "job": job.snapshot()}


@app.post("/api/jobs/stop")
def stop_job(body: StopBody = StopBody()):
    return jobs.stop(body.job_id)


@app.get("/api/logs/stream")
async def log_stream(request: Request):
    """SSE stream — event-driven: JobManager push qua asyncio.Queue."""
    queue = jobs.subscribe()

    def _payload(snap: dict[str, Any] | None) -> str:
        if snap is None:
            snap = {"status": "idle", "running": False, "logs": []}
        snap = {**snap, "queue": jobs.queue_info()}
        return f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"

    async def gen():
        last_id = ""
        last_seq = 0
        try:
            j = jobs.current() or _last_job()
            if j is not None:
                snap = j.snapshot()
                last_id, last_seq = j.id, snap["log_seq"]
                yield _payload(snap)
            else:
                yield _payload(None)
            while True:
                if await request.is_disconnected():
                    return
                try:
                    await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # keep-alive comment; client sees nothing change
                    yield ": ping\n\n"
                    continue
                # coalesce: gộp các event dồn đến thành 1 snapshot
                while True:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                j = jobs.current() or _last_job()
                if j is None:
                    last_id, last_seq = "", 0
                    yield _payload(None)
                    continue
                # job đổi → gửi lại từ đầu buffer, không phải offset cũ
                log_from = last_seq if j.id == last_id else 0
                snap = j.snapshot(log_from=log_from)
                last_id, last_seq = j.id, snap["log_seq"]
                yield _payload(snap)
        finally:
            jobs.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/solver")
def solver_status():
    cfg = load_config()
    try:
        solver_manager.configure_from_settings(cfg)
    except Exception:
        pass
    status = solver_manager.get_status()
    status["notify_configured"] = notifier.configured()
    status["monitor_interval"] = solver_monitor.interval
    return status


@app.post("/api/solver")
def solver_action(body: SolverActionBody):
    if body.action not in ("start", "stop", "restart"):
        raise HTTPException(400, "action phải là start | stop | restart")

    def _do() -> None:
        cfg = load_config()
        try:
            if body.action == "start":
                solver_manager.start(cfg, force=True)
            elif body.action == "stop":
                solver_manager.stop()
            else:
                solver_manager.restart(cfg)
        except Exception:
            logger.exception("[solver] action %s failed", body.action)

    threading.Thread(target=_do, daemon=True, name="solver-action").start()
    return {"ok": True, "message": f"Đang {body.action} solver — xem trạng thái sau vài giây"}


class DockerActionBody(BaseModel):
    action: str = "start_daemon"  # start_daemon | start | stop | restart
    name: Optional[str] = None    # tên container (bắt buộc với start/stop/restart)


@app.get("/api/docker")
def docker_status():
    """Trạng thái Docker CLI + daemon + danh sách container."""
    out: dict[str, Any] = {
        "installed": shutil.which("docker") is not None,
        "daemon_running": False,
        "version": "",
        "containers": [],
        "desktop_found": False,
    }
    if not out["installed"]:
        return out
    exe = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
    out["desktop_found"] = exe.exists()
    try:
        v = subprocess.run(
            ["docker", "--version"], capture_output=True, text=True,
            timeout=6, encoding="utf-8", errors="replace",
        )
        out["version"] = (v.stdout or "").strip()
    except Exception:
        logger.debug("[docker] version probe failed", exc_info=True)
    try:
        r = subprocess.run(
            ["docker", "ps", "-a", "--format",
             "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.State}}"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if r.returncode == 0:
            out["daemon_running"] = True
            for line in (r.stdout or "").splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    out["containers"].append({
                        "name": parts[0], "image": parts[1],
                        "status": parts[2], "state": parts[3],
                    })
    except Exception:
        logger.debug("[docker] ps failed (daemon offline?)", exc_info=True)
    return out


@app.post("/api/docker")
def docker_action(body: DockerActionBody):
    if body.action not in ("start_daemon", "start", "stop", "restart"):
        raise HTTPException(400, "action phải là start_daemon | start | stop | restart")
    if body.action != "start_daemon" and not body.name:
        raise HTTPException(400, "cần tên container")

    def _do() -> None:
        try:
            if body.action == "start_daemon":
                if os.name == "nt":
                    exe = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
                    if exe.exists():
                        subprocess.Popen([str(exe)], close_fds=True)
                        return
                subprocess.run(["systemctl", "start", "docker"], timeout=30)
            else:
                subprocess.run(
                    ["docker", body.action, body.name], capture_output=True,
                    text=True, timeout=60, encoding="utf-8", errors="replace",
                )
        except Exception:
            logger.exception("[docker] action %s failed", body.action)

    threading.Thread(target=_do, daemon=True, name="docker-action").start()
    if body.action == "start_daemon":
        return {"ok": True, "message": "Đang bật Docker Desktop — chờ ~30s rồi bấm Refresh"}
    return {"ok": True, "message": f"Đang {body.action} {body.name} — xem lại sau vài giây"}


@app.get("/api/mail/lookup")
def mail_lookup(address: str = Query(..., min_length=5)):
    """Đọc hộp thư tmail.wibucrypto.pro của địa chỉ bất kỳ (kể cả hộp cũ) —
    trả danh sách mail kèm mã OTP 6 số để khỏi vào UI tmail."""
    address = address.strip().lower()
    if "@" not in address or "." not in address.split("@")[-1]:
        raise HTTPException(400, "address phải dạng ten@domain")
    from grokreg.mail.tmail_wibu import TmailWibuProvider

    cfg = load_config()
    tmail = TmailWibuProvider(dict(cfg.get("tmail_wibu") or {}))
    try:
        msgs, _html = tmail._fetch_messages(address, {})
    except Exception as e:
        raise HTTPException(502, f"tmail lỗi: {e}")
    out = []
    for m in msgs or []:
        blob = tmail._msg_blob(m)
        codes: list[str] = []
        for c in re.findall(r"\b(\d{6})\b", f"{m.get('subject') or ''} {blob}"):
            if c == "000000":
                continue  # số placeholder trong template mail Canva
            if c not in codes:
                codes.append(c)
        out.append(
            {
                "subject": str(m.get("subject") or "")[:140],
                "from": str(m.get("from") or ""),
                "time": str(
                    m.get("created_at") or m.get("time") or m.get("date") or ""
                ),
                "codes": codes[:3],
                "preview": re.sub(r"<[^>]+>", " ", blob)[:220],
            }
        )
    return {"ok": True, "address": address, "count": len(out), "messages": out}


class RerunBody(BaseModel):
    params: Optional[dict[str, Any]] = None


@app.get("/api/dashboard")
def dashboard(days: int = Query(14, ge=1, le=90)):
    return dashboard_stats_mod.dashboard_stats(ROOT, days=days)


@app.get("/api/health/accounts")
def health_accounts():
    """Kết quả health check lần gần nhất (cache) — không gọi ra ngoài."""
    state = health_check_mod.load_state(ROOT)
    if not state:
        return {"configured": None, "checked_at": 0, "alive": 0, "dead": 0,
                "unknown": 0, "total": 0, "accounts": []}
    accounts = [
        {"id": k, **v}
        for k, v in sorted(
            (state.get("results") or {}).items(), key=lambda kv: kv[1].get("name", "")
        )[:500]
    ]
    return {
        "configured": state.get("configured"),
        "checked_at": state.get("checked_at", 0),
        "total": state.get("total", len(accounts)),
        "alive": state.get("alive", 0),
        "dead": state.get("dead", 0),
        "unknown": state.get("unknown", 0),
        "accounts": accounts,
    }


@app.post("/api/health/run")
def health_run():
    """Bấm chạy health check tay — gọi Sub2API admin, có thể mất vài giây."""
    return health_check_mod.run_check(ROOT)


@app.get("/api/backups")
def backups_list():
    """Danh sách bản backup data/ hiện có."""
    return backup_mod.list_backups(ROOT)


@app.post("/api/backups/run")
def backups_run():
    """Backup ngay (idempotent trong ngày — hôm nay có rồi thì skip)."""
    return backup_mod.run_backup(ROOT)


@app.post("/api/jobs/{job_id}/rerun")
def rerun_job(job_id: str, body: RerunBody = RerunBody()):
    """Re-run job cũ với params đã lưu (hoặc override mới)."""
    old = jobs.get(job_id)
    if not old:
        raise HTTPException(404, "job not found")
    params = dict(body.params if body.params is not None else old.params or {})
    try:
        job = jobs.start(old.tool_id, params)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "job": job.snapshot()}


@app.get("/api/config")
def get_config():
    """Redacted config — secrets never leave /api/config/summary either."""
    return config_summary()


@app.get("/api/config/summary")
def config_summary():
    """Safe subset for UI (no full secrets dump in list)."""
    cfg_path = ROOT / "config.json"
    raw: dict[str, Any] = {}
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
    sub = raw.get("sub2api") or {}
    gs = raw.get("google_sheets") or {}
    return {
        "email_provider": raw.get("email_provider"),
        "fixed_password_set": bool(raw.get("fixed_password")),
        "sub2api": {
            "enabled": sub.get("enabled", True),
            "mode": sub.get("mode", "auto"),
            "url": sub.get("sub2api_url", ""),
            "group": sub.get("group", "grok free"),
            "name_prefix": sub.get("name_prefix", "grok free"),
            "user": sub.get("sub2api_user", ""),
        },
        "google_sheets": {
            "enabled": gs.get("enabled", False),
            "spreadsheet_id": gs.get("spreadsheet_id", ""),
            "webapp_set": bool(gs.get("webapp_url")),
        },
        "force_guest_on_start": raw.get("force_guest_on_start"),
        "open_grok_after_success": raw.get("open_grok_after_success"),
    }


def main():
    import os
    import uvicorn

    # Windows console often defaults to cp1252 — force UTF-8 so prints don't crash
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    host = os.environ.get("WEB_HOST") or "127.0.0.1"
    port = int(os.environ.get("WEB_PORT") or 8787)
    url = f"http://{host}:{port}/"
    banner = f"\n  Draco Reg  v{__version__}\n  Open: {url}\n"
    try:
        print(banner)
    except Exception:
        sys.stdout.buffer.write(banner.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(
        "web_console.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
