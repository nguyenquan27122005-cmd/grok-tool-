"""SANDBOX reg song song — thí nghiệm tốc độ, không đụng tool chính.

- Không ghi Google Sheet (trừ khi --sheet)
- Ghi acc vào data/accounts_sandbox.txt (tách khỏi accounts.txt thật)
- Không redeem sau reg
- N luồng Chrome song song, mỗi luồng một debug port riêng

Chạy:  venv python sandbox/sandbox_reg.py 3 --count 6
       (3 luồng, tổng 6 acc; thêm --sheet để cho phép ghi sheet)
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canreg.config import load_config
from canreg.log import setup_logging
from canreg.stop import clear_stop
from canreg.worker import run_batch


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("threads", nargs="?", type=int, default=3, help="1-8 luồng Chrome")
    p.add_argument("--count", "-n", type=int, default=6, help="tổng số acc cần reg")
    p.add_argument("--sheet", action="store_true", help="cho phép ghi Google Sheet")
    a = p.parse_args()

    setup_logging()
    clear_stop()
    cfg = load_config()
    cfg["email_provider"] = "tmail_wibu"
    cfg["reg_backend"] = "browser"
    cfg["chrome_parallel"] = True
    cfg["sheet_all_success"] = bool(a.sheet)
    cfg["save_file"] = "data/accounts_sandbox.txt"
    redeem = dict(cfg.get("redeem") or {})
    redeem["after_reg"] = False
    cfg["redeem"] = redeem
    cfg["inter_success_delay_min"] = 2
    cfg["inter_success_delay_max"] = 4

    threads = max(1, min(8, a.threads))
    t0 = time.time()
    rs = run_batch(cfg, a.count, threads=threads)
    dt = time.time() - t0
    ok = sum(1 for r in rs if r.ok)
    per = dt / max(1, len(rs))
    print(
        f"\n=== SANDBOX: {ok}/{len(rs)} OK · {dt:.0f}s tổng · {per:.1f}s/acc hiệu quả "
        f"({threads} luồng) ===",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
