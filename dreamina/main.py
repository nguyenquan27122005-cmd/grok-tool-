"""Dreamina (dreamina.capcut.com) reg — tái dùng nguyên engine Passport của CapCut.

Dreamina chỉ khác CapCut ở app_id: 513641 (CapCut web = 348188). Engine, mail,
checkpoint, Google Sheet đều của capreg — trỏ ROOT/CONFIG sang thư mục này.

Chạy:
  python main.py 4 --count 1        # guerrilla temp mail
  python main.py 1 --count 5 -t 2   # hotmail pool, 2 luồng
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPCUT_ROOT = ROOT.parent / "capcut"
if str(CAPCUT_ROOT) not in sys.path:
    sys.path.insert(0, str(CAPCUT_ROOT))

# Trỏ data + config của capreg sang dreamina TRƯỚC khi import module còn lại
import capreg.paths as _paths  # noqa: E402

_paths.ROOT = ROOT
_paths.DATA = ROOT / "data"
_paths.CONFIG_PATH = ROOT / "config.json"
_paths.ensure_grok_on_path()
_paths.DATA.mkdir(parents=True, exist_ok=True)

from capreg.config import load_config  # noqa: E402
from capreg.log import log, setup_logging  # noqa: E402
from capreg.stop import clear_stop, request_stop  # noqa: E402
from capreg.worker import run_batch  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="Dreamina register (engine CapCut Passport)")
    p.add_argument("mail", nargs="?", default="4", help="1=hotmail 2=azpop 4=guerrilla 5=domain riêng")
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Chạy tiếp batch chưa xong từ checkpoint")
    p.add_argument(
        "--threads", "-t", type=int, default=None, help="Số luồng song song (1-4; backend HTTP)"
    )
    p.add_argument("--backend", "-b", choices=("protocol", "http"), default="protocol")
    p.add_argument("--invite", default=None, help="Mã invite / redeem")
    p.add_argument("--custom-domain", dest="custom_domain", default=None,
                   help="Domain riêng khi mail=5 (VD nguyenquan.dpdns.org)")
    args = p.parse_args(argv)

    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail)
    if cfg["email_provider"] == "custom_domain":
        cfg["custom_domain"] = str(args.custom_domain or "nguyenquan.dpdns.org").strip().lstrip("@")
    cfg["reg_backend"] = "protocol"
    inv = (args.invite or os.environ.get("DREAMINA_INVITE") or "").strip()
    if inv:
        cfg["invite_code"] = inv

    count = args.count if args.count is not None else int(cfg.get("batch_count") or 1)

    clear_stop()
    log.info(
        "%s reg mail=%s backend=protocol count=%s app_id=%s",
        str(cfg.get("tool_label") or "DREAMINA"),
        cfg["email_provider"],
        "∞" if count <= 0 else count,
        cfg.get("app_id"),
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
