"""CLI: python main.py 1 --count 1 --backend browser"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gsparkreg.config import load_config
from gsparkreg.log import log, setup_logging
from gsparkreg.stop import clear_stop, request_stop
from gsparkreg.worker import run_batch


def _pick_mail(cli: str | None) -> str:
    if cli in ("1", "hotmail"):
        return "hotmail"
    if cli in ("2", "azpop", "azpopmail"):
        return "azpopmail"
    if cli in ("3", "tmail", "tmail_wibu", "wibu"):
        return "tmail_wibu"
    if cli in ("4", "guerrilla", "guerrillamail"):
        return "guerrilla"
    if cli in ("0", "auto_temp", "temp", "smart"):
        return "auto_temp"
    if cli in ("5", "custom", "custom_domain", "domain", "rieng"):
        return "custom_domain"
    return "hotmail"


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="Genspark.ai register (Azure AD B2C + CAPTCHA + OTP)")
    p.add_argument("mail", nargs="?", default="1", help="1=hotmail 2=azpop 3=tmail 4=guerrilla 0=smart 5=domain riêng")
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Tiếp tục batch chưa xong từ checkpoint")
    p.add_argument(
        "--threads", "-t", type=int, default=None, help="Số luồng song song (1-4; backend HTTP)"
    )
    p.add_argument("--backend", "-b", choices=("browser", "protocol", "auto", "gpm"), default=None)
    p.add_argument("--custom-domain", dest="custom_domain", default=None,
                   help="Domain riêng khi mail=5 (VD nguyenquan.dpdns.org)")
    p.add_argument(
        "--claim",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Sau reg: Claim My Free Month (Stripe $0). --no-claim để bỏ.",
    )
    args = p.parse_args(argv)

    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail)
    if cfg["email_provider"] == "custom_domain":
        cfg["custom_domain"] = str(args.custom_domain or "nguyenquan.dpdns.org").strip().lstrip("@")
    if args.backend:
        cfg["reg_backend"] = args.backend
    elif not cfg.get("reg_backend"):
        cfg["reg_backend"] = "browser"
    env_claim = os.environ.get("GENSPARK_CLAIM")
    if args.claim is not None:
        cfg["claim_free_month"] = bool(args.claim)
    elif env_claim is not None and str(env_claim).strip() != "":
        cfg["claim_free_month"] = str(env_claim).strip().lower() not in ("0", "false", "no", "off")
    count = args.count if args.count is not None else int(cfg.get("batch_count") or 1)
    clear_stop()
    log.info(
        "Genspark reg mail=%s backend=%s count=%s claim=%s",
        cfg["email_provider"],
        cfg.get("reg_backend"),
        "∞" if count <= 0 else count,
        cfg.get("claim_free_month", True),
    )
    try:
        run_batch(
            cfg,
            count,
            resume=bool(getattr(args, "resume", False)),
            threads=(args.threads if getattr(args, "threads", None) else int(cfg.get("threads") or 1)),
        )
    except KeyboardInterrupt:
        request_stop("Ctrl+C")
        log.info("Ctrl+C — dừng")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
