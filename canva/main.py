"""CLI: python main.py 1 --count 1 --backend auto"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canreg.config import load_config
from canreg.log import log, setup_logging
from canreg.stop import clear_stop, request_stop
from canreg.worker import run_batch


def _pick_mail(cli: str | None) -> str:
    if cli in ("1", "hotmail"):
        return "hotmail"
    if cli in ("2", "azpop", "azpopmail"):
        return "azpopmail"
    if cli in ("3", "tmail", "tmail_wibu", "tmailwibu", "wibu"):
        return "tmail_wibu"
    if cli in ("4", "guerrilla", "guerrillamail"):
        return "guerrilla"
    if cli in ("0", "auto_temp", "temp", "smart"):
        return "auto_temp"
    if cli in ("5", "custom", "custom_domain", "domain", "rieng"):
        return "custom_domain"
    return "hotmail"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("redeem", "reg"):
        from canva_tool import main as tool_main

        return tool_main(argv)
    setup_logging()
    p = argparse.ArgumentParser(description="Canva register")
    p.add_argument("mail", nargs="?", default="1", help="0=smart 1=hotmail 2=azpop 3=tmail 4=guerrilla 5=domain riêng")
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Tiếp tục batch chưa xong từ checkpoint")
    p.add_argument(
        "--threads", "-t", type=int, default=None, help="Số luồng song song (1-8; reg browser 6 luồng ≈ 20s/acc)"
    )
    p.add_argument("--backend", "-b", choices=("browser", "protocol", "auto"), default=None)
    p.add_argument("--custom-domain", dest="custom_domain", default=None,
                   help="Domain riêng khi mail=5 (VD nguyenquan.dpdns.org)")
    args = p.parse_args(argv)

    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail)
    if cfg["email_provider"] == "custom_domain":
        cfg["custom_domain"] = str(args.custom_domain or "nguyenquan.dpdns.org").strip().lstrip("@")
    if args.backend:
        cfg["reg_backend"] = args.backend
    elif not cfg.get("reg_backend"):
        cfg["reg_backend"] = "auto"
    claim_env = (os.environ.get("CANVA_SHEET_ALL") or "").strip().lower()
    if claim_env in ("0", "false", "no", "off"):
        cfg["sheet_all_success"] = False

    count = args.count if args.count is not None else int(cfg.get("batch_count") or 1)

    clear_stop()
    log.info(
        "Canva reg mail=%s backend=%s count=%s",
        cfg["email_provider"],
        cfg.get("reg_backend"),
        "∞" if count <= 0 else count,
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
