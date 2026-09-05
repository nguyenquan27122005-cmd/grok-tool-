"""CLI: python main.py 2 --count 1 --backend protocol"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capreg.config import load_config
from capreg.log import log, setup_logging
from capreg.stop import clear_stop, request_stop
from capreg.worker import run_batch


def _pick_mail(cli: str | None) -> str:
    if cli in ("1", "hotmail"):
        return "hotmail"
    if cli in ("2", "azpop", "azpopmail"):
        return "azpopmail"
    if cli in ("3", "tmail", "tmail_wibu", "tmailwibu", "wibu"):
        return "tmail_wibu"
    if cli in ("5", "custom", "custom_domain", "domain", "rieng"):
        return "custom_domain"
    return "guerrilla"


def _check_session(cfg: dict, session_key: str) -> int:
    from capreg.api import new_client
    from capreg.offers import check_active_offers, claim_new_user_offers

    key = (session_key or "").strip()
    if not key:
        log.error("Thiếu session_key")
        return 2
    client = new_client(cfg)
    if cfg.get("claim_offer") is not False:
        claim = claim_new_user_offers(client, cfg, session_key=key)
        log.info("[check] claim=%s", claim.get("label"))
    info = check_active_offers(client, cfg, session_key=key)
    log.info(
        "OFFER  summary=%s  pro=%s  trial=%s  plan=%s  expire=%s  avail=%s",
        info.get("summary"),
        info.get("is_pro"),
        info.get("is_trial"),
        info.get("plan") or "—",
        info.get("expire") or "—",
        info.get("offers_available") or [],
    )
    return 0 if info.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="CapCut register")
    p.add_argument("mail", nargs="?", default="4", help="1=hotmail 2=azpop 4=guerrilla")
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Tiếp tục batch chưa xong từ checkpoint")
    p.add_argument(
        "--threads", "-t", type=int, default=None, help="Số luồng song song (1-4, mặc định 1; backend HTTP)"
    )
    p.add_argument("--backend", "-b", choices=("protocol", "http"), default="protocol")
    p.add_argument("--invite", default=None, help="Mã invite / redeem")
    p.add_argument("--custom-domain", dest="custom_domain", default=None,
                   help="Domain riêng khi mail=5 (VD nguyenquan.dpdns.org)")
    p.add_argument(
        "--check-session",
        nargs="?",
        const="LAST",
        default=None,
        help="Chỉ check offer. Không ghi = dùng data/last_session.json",
    )
    args = p.parse_args(argv)

    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail)
    if cfg["email_provider"] == "custom_domain":
        cfg["custom_domain"] = str(args.custom_domain or "nguyenquan.dpdns.org").strip().lstrip("@")
    cfg["reg_backend"] = "protocol"
    inv = (args.invite or os.environ.get("CAPCUT_INVITE") or "").strip()
    if inv:
        cfg["invite_code"] = inv
    claim_env = (os.environ.get("CAPCUT_CLAIM") or "").strip().lower()
    if claim_env in ("0", "false", "no", "off"):
        cfg["claim_offer"] = False
    elif claim_env in ("1", "true", "yes", "on"):
        cfg["claim_offer"] = True

    if args.check_session is not None:
        key = args.check_session
        if key == "LAST":
            import json

            pth = ROOT / "data" / "last_session.json"
            if not pth.exists():
                log.error("Không có %s — reg 1 acc trước", pth)
                return 2
            try:
                key = str(json.loads(pth.read_text(encoding="utf-8")).get("session_key") or "")
            except Exception as e:
                log.error("Đọc last_session: %s", e)
                return 2
        return _check_session(cfg, key)

    count = args.count if args.count is not None else int(cfg.get("batch_count") or 1)

    clear_stop()
    log.info(
        "CapCut reg mail=%s backend=protocol count=%s claim=%s invite=%s",
        cfg["email_provider"],
        "∞" if count <= 0 else count,
        cfg.get("claim_offer", True),
        "yes" if cfg.get("invite_code") else "no",
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
