"""CLI: python main.py 1 --count 5 (mail positional chỉ để tương thích — luôn Hotmail)"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaireg.config import load_config
from zaireg.log import log, setup_logging
from zaireg.stop import clear_stop
from zaireg.worker import run_batch


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="Z.ai / ZCode register (Hotmail pool)")
    # z.ai chặn domain temp (EMAIL_DOMAIN_BLOCKED) — luôn Hotmail, tham số cũ
    # (1/2/4) được nhận nhưng bỏ qua để CLI/web cũ không vỡ
    p.add_argument("mail", nargs="?", default="1", help=argparse.SUPPRESS)
    p.add_argument("--count", "-n", type=int, default=None)
    p.add_argument("--resume", action="store_true", help="Tiếp tục batch chưa xong từ checkpoint")
    p.add_argument(
        "--threads", "-t", type=int, default=None, help="Số luồng song song (1-4, mặc định 1; backend HTTP)"
    )
    p.add_argument("--backend", "-b", choices=("protocol", "http"), default="protocol")
    args = p.parse_args(argv)

    cfg = load_config()
    cfg["email_provider"] = "hotmail"
    cfg["reg_backend"] = "protocol"
    claim_env = (os.environ.get("ZAI_CLAIM") or "").strip().lower()
    if claim_env in ("0", "false", "no", "off"):
        cfg["claim_offer"] = False

    n = args.count if args.count is not None else int(cfg.get("batch_count") or 1)
    log.info(
        "Z.ai reg mail=%s backend=protocol count=%s",
        cfg["email_provider"],
        n if n > 0 else "∞",
    )
    clear_stop()
    run_batch(cfg, n, resume=bool(getattr(args, "resume", False)), threads=(args.threads if getattr(args, "threads", None) else int(cfg.get("threads") or 1)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
