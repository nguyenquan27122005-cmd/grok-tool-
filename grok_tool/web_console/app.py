"""
Web control plane — multi-tool registration console.
Run:  python -m web_console.app
   or CHAY_WEB.bat
"""

from __future__ import annotations

import asyncio
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_console import __version__
from web_console.job_manager import JobManager
from web_console.plugins import all_plugins, get_plugin

STATIC = Path(__file__).resolve().parent / "static"
TEMPLATES = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Reg Control Plane", version=__version__)
jobs = JobManager(ROOT)

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


def resolve_brand_icon(tool_id: str, explicit: str = "") -> str:
    """Official publisher icon. Drop brands/{id}.svg|png|webp — future tools inherit."""
    if explicit:
        return str(explicit)
    brands = STATIC / "img" / "brands"
    for ext in (".svg", ".png", ".webp"):
        if (brands / f"{tool_id}{ext}").is_file():
            return f"/static/img/brands/{tool_id}{ext}"
    return ""


def _tool_public(p) -> dict[str, Any]:
    m = p.meta
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description,
        "icon": m.icon,
        "brand_icon": resolve_brand_icon(m.id, getattr(m, "brand_icon", "") or ""),
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


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": jobs.list_jobs(), "current": (jobs.current().snapshot() if jobs.current() else None)}


@app.get("/api/jobs/current")
def current_job(log_from: int = 0):
    j = jobs.current()
    if not j:
        # last job if any
        allj = jobs.list_jobs(1)
        if allj:
            last = jobs.get(allj[0]["id"])
            if last:
                return last.snapshot(log_from=log_from)
        return {"status": "idle", "logs": [], "running": False}
    return j.snapshot(log_from=log_from)


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
async def log_stream():
    """SSE stream of current job logs."""

    async def gen():
        last_seq = 0
        last_status = ""
        while True:
            j = jobs.current()
            if j is None:
                # peek most recent finished
                listed = jobs.list_jobs(1)
                if listed:
                    j = jobs.get(listed[0]["id"])
            if j:
                snap = j.snapshot(log_from=last_seq)
                if snap["log_seq"] > last_seq or snap["status"] != last_status:
                    last_seq = snap["log_seq"]
                    last_status = snap["status"]
                    payload = json.dumps(snap, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                if snap["status"] not in ("running", "pending", "stopping"):
                    # one more tick then idle heartbeat
                    await asyncio.sleep(1.0)
            else:
                yield f"data: {json.dumps({'status': 'idle', 'running': False, 'logs': []})}\n\n"
            await asyncio.sleep(0.6)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/config")
def get_config():
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, str(e))


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
    banner = f"\n  Reg Control Plane  v{__version__}\n  Open: {url}\n"
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
