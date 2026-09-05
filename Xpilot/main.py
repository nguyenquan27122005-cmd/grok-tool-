"""CLI: python main.py 0 --count 1

Mail mặc định: temp (auto_temp) — X-Pilot KHÔNG chặn domain temp (đã test
tmail wibu) nhưng BẮT BUỘC OTP email verification. Signup thuần HTTP:
sendVerifyEmail → OTP → sign_up → sign_in lấy token. Free account có
350k video tokens.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpreg.config import load_config
from xpreg.log import log, setup_logging
from xpreg.stop import clear_stop, request_stop
from xpreg.worker import run_batch


def _pick_mail(cli: str | None, cfg: dict) -> str:
    if cli in ("1", "hotmail"):
        return "hotmail"
    if cli in ("3", "tmail", "tmail_wibu"):
        return "tmail_wibu"
    if cli in ("4", "spectxte", "tmail_spectxte"):
        return "tmail_spectxte"
    if cli in ("5", "custom", "custom_domain", "domain", "rieng"):
        return "custom_domain"
    if not cli or cli in ("0", "auto_temp", "temp", "2", "azpop", "azpopmail"):
        return "auto_temp"
    return "auto_temp"


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="X-Pilot register (HTTP + email OTP)")
    p.add_argument("mail", nargs="?", default="0",
                   help="0=temp (khuyên) 1=hotmail 2=azpop 3=tmail 4=spectxte 5=domain riêng — hoặc 'checkout' để lấy link thanh toán")
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Tiếp tục batch chưa xong từ checkpoint")
    p.add_argument("--threads", "-t", type=int, default=None,
                   help="Số luồng song song (1-8, mặc định 1; HTTP thuần nên song song thoải mái)")
    # checkout mode
    p.add_argument("--plans", default="creator", help="Checkout: gói, cách nhau dấu phẩy (creator,pro,ultra,business)")
    p.add_argument("--interval", default="monthly", choices=("monthly", "yearly"), help="Checkout: chu kỳ thanh toán")
    p.add_argument("--accounts", default="data/accounts.txt", help="Checkout: file account (email|password|...)")
    p.add_argument("--out", default="data/checkout_links.txt", help="Checkout: file ghi link")
    p.add_argument("--gsheet", action="store_true", help="Checkout: đẩy link vào Google Sheet (tab <tool>_checkout)")
    args = p.parse_args(argv)

    if (args.mail or "").strip().lower() == "checkout":
        from xpreg.checkout import run_checkout
        from xpreg.config import load_config as _lc
        from xpreg.stop import StopRequested

        clear_stop()
        plans = [x.strip().lower() for x in str(args.plans).split(",") if x.strip()]
        try:
            run_checkout(_lc(), plans=plans, interval=args.interval,
                         accounts_path=ROOT / args.accounts, out_path=ROOT / args.out,
                         push_sheet=bool(args.gsheet))
        except StopRequested as e:
            log.info("Stop: %s", e.reason)
        return 0

    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail, cfg)
    count = args.count if args.count is not None else int(cfg.get("batch_count") or 1)

    clear_stop()
    log.info(
        "X-Pilot reg mail=%s count=%s threads=%s",
        cfg["email_provider"],
        "∞" if count <= 0 else count,
        args.threads or int(cfg.get("threads") or 1),
    )
    try:
        run_batch(cfg, count, resume=bool(getattr(args, "resume", False)),
                  threads=(args.threads if getattr(args, "threads", None) else int(cfg.get("threads") or 1)))
    except KeyboardInterrupt:
        request_stop("Ctrl+C")
        log.info("Ctrl+C — dung")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
