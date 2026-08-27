#!/usr/bin/env python
"""Phân tích trace các job reg — chạy sau khi batch xong để có số liệu nâng cấp.

Nguồn dữ liệu:
  - data/logs/<job_id>.log      : log đầy đủ mỗi job (JobManager ghi)
  - <engine>/data/accounts.txt  : ledger kết quả từng engine
  - <engine>/data/batch_state.json : checkpoint batch đang dở

Dùng:  venv/Scripts/python.exe analyze_traces.py [job_id]
       (không đối số = phân tích tất cả job + ledger + checkpoint)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "data" / "logs"
ENGINES = {
    "grok": ROOT,
    "netflix": ROOT.parent / "netflix",
    "canva": ROOT.parent / "canva",
    "capcut": ROOT.parent / "capcut",
    "claude": ROOT.parent / "claude",
    "Heygen": ROOT.parent / "Heygen",
    "manus": ROOT.parent / "manus",
    "notion": ROOT.parent / "notion",
    "zai": ROOT.parent / "zai",
}

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]")

# stage marker → tên hiển thị (khớp theo substring, thứ tự ưu tiên)
STAGE_MARKS = [
    ("START", "=== START"),
    ("email acquire", "Email="),
    ("backend", "Backend"),
    ("captcha", "captcha"),
    ("turnstile", "Turnstile"),
    ("otp", "OTP"),
    ("otp", "otp"),
    ("sub2api", "Sub2API"),
    ("sub2api", "sub2api"),
    ("sheet", "Google Sheet"),
    ("sheet", "sheet"),
    ("offer", "offer"),
    ("redeem", "redeem"),
    ("DONE", "=== DONE"),
    ("STOP", ">>> STOP"),
]

ERR_BUCKETS = [
    ("otp_timeout", ["otp_timeout", "không thấy otp", "OTP timeout", "chờ OTP"]),
    ("mail/inbox", ["inbox", "guerrilla", "azpop", "tmail", "email_domain", "INELIGIBLE", "mail"]),
    ("captcha", ["captcha", "turnstile", "solver"]),
    ("rate/429", ["429", "rate-limit", "rate limit", "too many", "Rate-limit"]),
    ("browser", ["chrome", "browser", "pydoll", "timeouterror", "navigation"]),
    ("network", ["network", "connection", "reset", "ssl", "max retries"]),
    ("sub2api", ["sub2api"]),
    ("khác", []),
]


def _t2s(t: tuple[str, str, str]) -> int:
    return int(t[0]) * 3600 + int(t[1]) * 60 + int(t[2])


def parse_log(path: Path) -> dict:
    tool, stages, errs = "", [], Counter()
    first_ts = last_ts = None
    n_lines = 0
    final = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        n_lines += 1
        m = TS.match(raw)
        ts = (m.group(1), m.group(2), m.group(3)) if m else None
        if ts:
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        low = raw.lower()
        if "=== start tool=" in low and not tool:
            tool = raw.split("tool=")[-1].split(" ")[0]
        for name, pat in STAGE_MARKS:
            if pat.lower() in low:
                stages.append((name, raw[1:9] if raw.startswith("[") else "--:--:--"))
                break
        if any(k in low for k in ("error", "fail", "fatal", "❌")) or "warning" in low:
            for bucket, keys in ERR_BUCKETS:
                if any(k.lower() in low for k in keys) or (bucket == "khác" and not any(
                    k.lower() in low for b, ks in ERR_BUCKETS if b != "khác" for k in ks
                )):
                    errs[bucket] += 1
                    break
        if raw.startswith("=== DONE") or raw.startswith("=== STOPPED"):
            final = raw.strip("= ")
    dur = (_t2s(last_ts) - _t2s(first_ts)) if first_ts and last_ts else 0
    return {
        "file": path.name, "tool": tool, "lines": n_lines,
        "duration": dur, "stages": stages, "errors": errs, "final": final,
    }


def ledger_stats(engine_dir: Path) -> dict | None:
    p = engine_dir / "data" / "accounts.txt"
    if not p.exists():
        return None
    ok = fail = pending = total = 0
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "|" not in s:
            continue
        st = s.split("|")[2].strip().lower() if s.count("|") >= 2 else ""
        total += 1
        if st.startswith(("success", "added_sub2api", "need_payment", "redeem:sukses")):
            ok += 1
        elif st.startswith(("error", "redeem:fail")):
            fail += 1
        else:
            pending += 1
    return {"total": total, "ok": ok, "fail": fail, "pending": pending}


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(LOGS.glob("*.log")) if LOGS.exists() else []
    if only:
        files = [f for f in files if only in f.name]
    if not files:
        print("Chưa có log job nào trong data/logs/ — chạy job qua console trước.")
    for f in files:
        r = parse_log(f)
        print("=" * 66)
        print(f"JOB {r['file']}  tool={r['tool'] or '?'}  {r['lines']} dòng  ~{r['duration']}s")
        if r["final"]:
            print(f"  kết thúc: {r['final']}")
        print("  stages:")
        for name, ts in r["stages"][:40]:
            print(f"    [{ts}] {name}")
        if r["errors"]:
            print("  lỗi theo nhóm:")
            for bucket, cnt in r["errors"].most_common():
                print(f"    {bucket:14} {cnt}")
    print("=" * 66)
    print("LEDGER TỪNG ENGINE (accounts.txt):")
    for name, d in ENGINES.items():
        st = ledger_stats(d)
        if st and st["total"]:
            print(f"  {name:8} tổng {st['total']:4} | OK {st['ok']:4} | fail {st['fail']:4} | khác {st['pending']:3}")
    print("BATCH DỞ (checkpoint):")
    found = False
    for name, d in ENGINES.items():
        p = d / "data" / "batch_state.json"
        if p.exists():
            found = True
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
                print(f"  {name:8} còn {st.get('pending')} / {st.get('planned')} lượt (OK {st.get('ok')})")
            except Exception as e:
                print(f"  {name:8} lỗi đọc: {e}")
    if not found:
        print("  (không có — mọi batch đã xong)")


if __name__ == "__main__":
    main()
