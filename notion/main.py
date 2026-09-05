"""CLI: python main.py 3 --count 1 --backend browser  (3=tmail only)"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notreg.config import load_config
from notreg.log import log, setup_logging
from notreg.stop import clear_stop, request_stop
from notreg.worker import run_batch


def _pick_mail(cli: str | None) -> str:
    # Notion: mặc định tmail.wibucrypto.pro; "5" = domain riêng (forward→Hotmail)
    if cli in ("5", "custom", "custom_domain", "domain", "rieng"):
        return "custom_domain"
    return "tmail_wibu"


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="Notion register + check offer 1/3/6 tháng")
    p.add_argument("mail", nargs="?", default="3", help="3=tmail (mặc định) 5=domain riêng")
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Tiếp tục batch chưa xong từ checkpoint")
    p.add_argument(
        "--threads", "-t", type=int, default=None, help="Số luồng song song (1-4, mặc định 1; backend HTTP)"
    )
    p.add_argument("--backend", "-b", choices=("browser", "protocol", "auto"), default="browser")
    p.add_argument("--partner", default=None, help="Mã partner Notion for Startups (6 tháng)")
    p.add_argument("--until-success", action="store_true", help="Chạy đến khi reg OK")
    p.add_argument("--until-offer", action="store_true", help="Chạy đến khi có offer 1/3/6 tháng")
    p.add_argument("--custom-domain", dest="custom_domain", default=None,
                   help="Domain riêng khi mail=5 (VD nguyenquan.dpdns.org)")
    args = p.parse_args(argv)

    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail)
    if cfg["email_provider"] == "custom_domain":
        cfg["custom_domain"] = str(args.custom_domain or "nguyenquan.dpdns.org").strip().lstrip("@")
    if args.backend:
        cfg["reg_backend"] = args.backend
    partner = (args.partner or os.environ.get("NOTION_PARTNER") or "").strip()
    if partner:
        cfg.setdefault("startup", {})
        cfg["startup"]["partner_code"] = partner
        cfg["partner_code"] = partner
    if args.until_success:
        cfg["until_success"] = True
    if args.until_offer:
        cfg["until_offer"] = True
    count = args.count if args.count is not None else int(cfg.get("batch_count") or 1)
    if cfg.get("until_success") or cfg.get("until_offer"):
        count = 0

    clear_stop()
    log.info(
        "Notion reg mail=%s backend=%s count=%s until_success=%s until_offer=%s partner=%s",
        cfg["email_provider"],
        cfg.get("reg_backend"),
        "∞" if count <= 0 else count,
        bool(cfg.get("until_success")),
        bool(cfg.get("until_offer")),
        "yes" if partner else "no",
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
