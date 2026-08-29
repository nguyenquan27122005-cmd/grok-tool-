"""Driver test toàn bộ tool qua web console API — mỗi tool chạy 1 acc rồi stop.

Chạy: venv/Scripts/python.exe scripts/test_all_tools.py
Mỗi tool: start job → poll → stop khi (task #1 xong & task #2 bắt đầu) hoặc
status kết thúc, hoặc timeout → in tóm tắt: status, exit_code, log tail.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8787"

# (tool_id, params) — tôn trọng default của từng tool, ép count=1 cho tool temp-mail
TOOLS: list[tuple[str, dict]] = [
    ("heygen", {"count": 1}),
    ("capcut", {"count": 1}),
    ("zai", {"count": 1}),
    ("dreamina", {"mail": "4", "count": 1, "backend": "protocol",
                  "custom_domain": "nguyenquan.dpdns.org"}),
    ("manus", {"count": 1}),
    ("canva", {"mail": "1", "count": 1, "backend": "browser"}),
    ("netflix", {"mail": "1", "count": 1, "backend": "browser"}),
    ("claude", {"mail": "1", "count": 1, "backend": "browser"}),
    ("genspark", {"mail": "1", "count": 1, "backend": "browser"}),
    ("notion", {}),
    ("chatgpt", {}),
    ("openai", {}),
]

POLL_SEC = 15
HARD_TIMEOUT_SEC = 8 * 60


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def run_tool(tool_id: str, params: dict) -> dict:
    out: dict = {"tool": tool_id, "job_id": "", "status": "-", "exit": None,
                 "success": False, "err": "", "log_tail": []}
    try:
        started = _req("POST", "/api/jobs/start", {"tool_id": tool_id, "params": params})
    except Exception as e:
        out["err"] = f"start failed: {e}"
        return out
    j = started.get("job") or {}
    jid = j.get("id") or ""
    out["job_id"] = jid
    if not jid:
        out["err"] = f"no job id: {started}"
        return out

    t0 = time.time()
    saw_success = False
    saw_task2 = False
    while time.time() - t0 < HARD_TIMEOUT_SEC:
        time.sleep(POLL_SEC)
        try:
            snap = _req("GET", f"/api/jobs/{jid}")
        except Exception as e:
            out["err"] = f"poll error: {e}"
            break
        job = snap.get("job") or snap
        status = job.get("status")
        logs = job.get("logs") or []
        text = "\n".join(str(x) for x in logs)
        if "THÀNH CÔNG" in text or "imported" in text or "success" in text.lower():
            saw_success = True
        if "Task #2/" in text or "2] Task #2" in text or "Task #2" in text:
            saw_task2 = True
        out["status"] = status
        out["exit"] = job.get("exit_code")
        out["log_tail"] = [str(x) for x in logs[-6:]]
        if status in ("done", "stopped", "failed", "error"):
            break
        if saw_success and saw_task2:
            _req("POST", "/api/jobs/stop", {"job_id": jid})
            time.sleep(3)
            try:
                snap = _req("GET", f"/api/jobs/{jid}")
                job = snap.get("job") or snap
                out["status"] = job.get("status")
                out["exit"] = job.get("exit_code")
                out["log_tail"] = [str(x) for x in (job.get("logs") or [])[-6:]]
            except Exception:
                pass
            break
    out["success"] = saw_success
    return out


def main() -> int:
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    results = []
    for tool_id, params in TOOLS:
        if only and tool_id not in only:
            continue
        print(f"\n{'=' * 60}\n>>> TOOL {tool_id} params={params}", flush=True)
        res = run_tool(tool_id, params)
        results.append(res)
        print(f"<<< {tool_id}: status={res['status']} exit={res['exit']} "
              f"success_mark={res['success']} err={res['err']}", flush=True)
        for line in res["log_tail"]:
            print(f"    | {line[:150]}", flush=True)
    print("\n" + "=" * 60 + "\nSUMMARY")
    for r in results:
        mark = "OK " if r["success"] else ("ERR" if r["err"] or r["status"] in ("failed", "error") else "?  ")
        print(f"  [{mark}] {r['tool']:10s} status={r['status']:8s} exit={r['exit']} err={r['err'][:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
