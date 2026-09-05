"""Test reg 1 acc Claude bằng backend GPM với combo do người dùng cung cấp.

Pool mail trỏ vào data/_test_combo_hotmails.txt (đúng 1 combo) và Google
Sheets bị tắt để không đẩy dữ liệu test lên sheet thật.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from claudereg.config import load_config
from claudereg.log import setup_logging
from claudereg.stop import clear_stop
from claudereg.worker import run_batch


def main() -> int:
    setup_logging()
    cfg = load_config()
    cfg["email_provider"] = "hotmail"
    cfg["reg_backend"] = "gpm"
    cfg["hotmail_list"] = str(ROOT / "data" / "_test_combo_hotmails.txt")
    cfg["google_sheets"] = {"enabled": False}
    clear_stop()
    results = run_batch(cfg, 1)
    for r in results:
        print(f"RESULT: {r!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
