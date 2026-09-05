"""CLI: python main.py 2 --count 1 --backend browser"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from manreg.config import load_config
from manreg.log import log, setup_logging
from manreg.stop import clear_stop, request_stop
from manreg.worker import run_batch


def _pick_mail(cli: str | None) -> str:
    if cli in ("1", "hotmail"):
        return "hotmail"
    if cli in ("2", "azpop", "azpopmail"):
        return "azpopmail"
    if cli in ("4", "guerrilla", "guerrillamail"):
        return "guerrilla"
    if cli in ("3", "tmail", "tmail_wibu"):
        return "tmail_wibu"
    if cli in ("0", "auto_temp", "temp"):
        return "azpopmail"
    return "azpopmail"


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="Manus register")
    p.add_argument("mail", nargs="?", default="2", help="1=hotmail 2=azpop 3=tmail 4=guerrilla")
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Tiếp tục batch chưa xong từ checkpoint")
    p.add_argument(
        "--threads", "-t", type=int, default=None, help="Số luồng song song (1-4, mặc định 1; backend HTTP)"
    )
    p.add_argument("--backend", "-b", choices=("browser", "protocol", "auto", "gpm"), default="browser")
    p.add_argument("--invite", default=None, help="Mã invite nếu Manus còn hỏi")
    p.add_argument("--until-success", action="store_true", help="Chạy đến khi reg OK")
    args = p.parse_args(argv)

    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail)
    if args.backend:
        cfg["reg_backend"] = args.backend
    inv = (args.invite or os.environ.get("MANUS_INVITE") or "").strip()
    if inv:
        cfg["invite_code"] = inv
    if args.until_success:
        cfg["until_success"] = True
    count = args.count if args.count is not None else int(cfg.get("batch_count") or 1)
    if cfg.get("until_success"):
        count = 0

    clear_stop()
    log.info(
        "Manus reg mail=%s backend=%s count=%s invite=%s until_success=%s",
        cfg["email_provider"],
        cfg.get("reg_backend"),
        "∞" if count <= 0 else count,
        "yes" if cfg.get("invite_code") else "no",
        bool(cfg.get("until_success")),
    )
    try:
        run_batch(cfg, count, resume=bool(getattr(args, "resume", False)), threads=(args.threads if getattr(args, "threads", None) else int(cfg.get("threads") or 1)))
    except KeyboardInterrupt:
        request_stop("Ctrl+C")
        log.info("Ctrl+C — dừng")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
