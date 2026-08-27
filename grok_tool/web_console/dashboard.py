"""Dashboard stats — tổng hợp số liệu cho trang Dashboard (biểu đồ).

Nguồn dữ liệu:
- data/jobs.jsonl  → job runs theo ngày, tỷ lệ done/error/stopped
- data/accounts.txt → reg OK/fail/pending (ledger không lưu timestamp từng
  dòng nên vẽ theo tổng; jobs.jsonl có created_at nên vẽ được theo ngày)

API trả về shape gọn để frontend vẽ SVG chart thuần (không cần thư viện).
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DAYS_DEFAULT = 14


def _read_jobs(root: Path) -> list[dict[str, Any]]:
    """Đọc jobs.jsonl — mỗi dòng 1 job record (đã redact)."""
    p = root / "data" / "jobs.jsonl"
    out: list[dict[str, Any]] = []
    if not p.is_file():
        return out
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    except Exception:
        pass
    return out


def _read_ledger(root: Path) -> list[dict[str, Any]]:
    """Đọc accounts.txt — email|password|status."""
    p = root / "data" / "accounts.txt"
    rows: list[dict[str, Any]] = []
    if not p.is_file():
        return rows
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            rows.append(
                {
                    "email": parts[0].strip(),
                    "password": parts[1],
                    "status": parts[2].strip(),
                }
            )
    except Exception:
        pass
    return rows


def _day_key(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def dashboard_stats(root: Path, days: int = DAYS_DEFAULT) -> dict[str, Any]:
    days = max(1, min(90, int(days)))
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    day_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    labels = [d.strftime("%m-%d") for d in day_list]
    keys = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(day_list)}

    # ── jobs ──
    jobs = _read_jobs(root)
    jobs_per_day = [0] * days
    status_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    durations: list[float] = []
    last_ended = 0.0
    for j in jobs:
        st = str(j.get("status") or "?")
        status_counts[st] += 1
        tool_counts[str(j.get("tool_id") or "?")] += 1
        ended = float(j.get("ended_at") or 0)
        started = float(j.get("started_at") or 0)
        if ended > last_ended:
            last_ended = ended
        day = _day_key(float(j.get("created_at") or ended or 0))
        idx = keys.get(day)
        if idx is not None:
            jobs_per_day[idx] += 1
        if started and ended and ended > started:
            durations.append(ended - started)

    # ── ledger ──
    rows = _read_ledger(root)
    ok_rows = fail_rows = pending_rows = 0
    for r in rows:
        st = r["status"]
        if st.startswith("success") or st.startswith("added_sub2api"):
            ok_rows += 1
        elif st.startswith("error") or st == "otp_timeout":
            fail_rows += 1
        else:
            pending_rows += 1

    avg_dur = round(sum(durations) / len(durations), 1) if durations else 0.0
    success_rate = (
        round(ok_rows / max(1, ok_rows + fail_rows) * 100, 1)
        if (ok_rows + fail_rows)
        else 0.0
    )

    return {
        "days": days,
        "labels": labels,
        "jobs_per_day": jobs_per_day,
        "job_status": dict(status_counts),
        "tool_runs": dict(tool_counts.most_common()),
        "ledger": {
            "total": len(rows),
            "ok": ok_rows,
            "fail": fail_rows,
            "pending": pending_rows,
            "success_rate": success_rate,
        },
        "jobs": {
            "total": len(jobs),
            "avg_duration_sec": avg_dur,
            "last_run_at": last_ended,
        },
        "generated_at": time.time(),
    }