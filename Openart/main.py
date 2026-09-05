"""CLI: python main.py 1 --count 1 --backend protocol

Mail mặc định: Hotmail (1) — OpenArt (Clerk) chặn domain temp (azpop/tmail)
từ 2026-09. Các mã temp vẫn để sẵn để test/backup.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oareg.config import load_config
from oareg.log import log, setup_logging
from oareg.stop import clear_stop, request_stop
from oareg.worker import run_batch


def _pick_mail(cli: str | None, cfg: dict) -> str:
    if cli in ("1", "hotmail"):
        return "hotmail"
    if cli in ("3", "tmail", "tmail_wibu"):
        return "tmail_wibu"
    if cli in ("5", "custom", "custom_domain", "domain", "rieng"):
        return "custom_domain"
    if not cli or cli in ("0", "auto_temp", "temp", "2", "azpop", "azpopmail"):
        return "azpopmail"
    return "azpopmail"


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="OpenArt register (Clerk email_code)")
    p.add_argument("mail", nargs="?", default="1", help="1=hotmail (khuyên) 2=azpop 3=tmail 5=domain riêng")
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Tiếp tục batch chưa xong từ checkpoint")
    p.add_argument(
        "--threads", "-t", type=int, default=None, help="Số luồng song song (1-4, mặc định 1; backend HTTP)"
    )
    p.add_argument("--backend", "-b", choices=("protocol",), default="protocol")
    p.add_argument("--custom-domain", dest="custom_domain", default=None,
                   help="Domain riêng khi mail=5 (VD nguyenquan.dpdns.org)")
    # checkout mode
    p.add_argument("--plans", default="starter", help="Checkout: gói, cách nhau dấu phẩy (starter,plus,pro,wonder,team)")
    p.add_argument("--interval", default="month", choices=("year", "month"), help="Checkout: chu kỳ thanh toán")
    p.add_argument("--accounts", default="data/accounts.txt", help="Checkout: file account")
    p.add_argument("--out", default="data/checkout_links.txt", help="Checkout: file ghi link")
    p.add_argument("--gsheet", action="store_true", help="Checkout: đẩy link vào Google Sheet (tab <tool>_checkout)")
    # pay mode — điền card CỦA MÌNH vào Stripe checkout
    p.add_argument("--cards", default="data/cards.txt", help="Pay: file card PAN|MM|YY|CVC|tên|zip")
    p.add_argument("--limit", type=int, default=0, help="Pay: số account tối đa (0 = tất cả)")
    p.add_argument("--show", action="store_true", help="Pay: hiện browser để debug")
    args = p.parse_args(argv)

    mode = (args.mail or "").strip().lower()
    if mode == "checkout":
        from oareg.checkout import run_checkout
        from oareg.stop import StopRequested

        clear_stop()
        plans = [x.strip().lower() for x in str(args.plans).split(",") if x.strip()]
        try:
            run_checkout(None, plans=plans, interval=args.interval,
                         accounts_path=ROOT / args.accounts, out_path=ROOT / args.out,
                         push_sheet=bool(args.gsheet))
        except StopRequested as e:
            log.info("Stop: %s", e.reason)
        return 0

    if mode == "pay":
        from oareg.pay import run_pay
        from oareg.stop import StopRequested

        clear_stop()
        plans = [x.strip().lower() for x in str(args.plans).split(",") if x.strip()]
        try:
            run_pay(plans, args.interval, accounts_path=ROOT / args.accounts,
                    cards_path=ROOT / args.cards, limit=int(args.limit or 0),
                    show=bool(args.show))
        except StopRequested as e:
            log.info("Stop: %s", e.reason)
        return 0

    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail, cfg)
    if cfg["email_provider"] == "custom_domain":
        cfg["custom_domain"] = str(args.custom_domain or "nguyenquan.dpdns.org").strip().lstrip("@")
    if args.backend:
        cfg["reg_backend"] = args.backend
    count = args.count if args.count is not None else int(cfg.get("batch_count") or 1)

    clear_stop()
    log.info(
        "OpenArt reg mail=%s backend=%s count=%s",
        cfg["email_provider"],
        cfg.get("reg_backend"),
        "∞" if count <= 0 else count,
    )
    try:
        run_batch(cfg, count, resume=bool(getattr(args, "resume", False)), threads=(args.threads if getattr(args, "threads", None) else int(cfg.get("threads") or 1)))
    except KeyboardInterrupt:
        request_stop("Ctrl+C")
        log.info("Ctrl+C — dung")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
