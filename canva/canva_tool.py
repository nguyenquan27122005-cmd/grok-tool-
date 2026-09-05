"""CLI Canva: reg + redeem.

python canva_tool.py 1 --count 1 --backend browser
python canva_tool.py redeem --accounts data/accounts.txt --codes data/codes.txt --threads 3 --output data/proof.json
"""

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
from canreg.paths import DATA
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
    return "hotmail"


def _resolve(p: str | None, default: Path) -> Path:
    if not p:
        return default
    path = Path(p)
    if not path.is_absolute():
        path = ROOT / path
    return path


def cmd_reg(args: argparse.Namespace) -> int:
    cfg = load_config()
    cfg["email_provider"] = _pick_mail(args.mail)
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
    run_batch(cfg, count)
    return 0


def cmd_redeem(args: argparse.Namespace) -> int:
    from canreg.redeem import run_redeem

    cfg = load_config()
    if args.threads:
        cfg["redeem_threads"] = args.threads
    accs = _resolve(args.accounts, DATA / "accounts.txt")
    codes = _resolve(args.codes, DATA / "codes.txt")
    proxy = _resolve(args.proxy, DATA / "proxy.txt") if args.proxy else None
    if args.proxy and not proxy.exists():
        # cho phép file tương đối hoặc tuyệt đối ngoài tool
        alt = Path(args.proxy)
        proxy = alt if alt.exists() else proxy
    out = _resolve(args.output, DATA / "proof.json")
    clear_stop()
    log.info("Canva redeem accs=%s codes=%s threads=%s", accs, codes, args.threads)
    run_redeem(
        cfg,
        accounts_path=accs,
        codes_path=codes,
        proxy_path=proxy if proxy and proxy.exists() else None,
        threads=int(args.threads or 3),
        output=out,
        success_only=bool(args.success_only),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(description="Canva tool - reg + redeem trial/promo")
    sub = p.add_subparsers(dest="cmd")

    pr = sub.add_parser("reg", help="Register Canva accounts")
    pr.add_argument("mail", nargs="?", default="1")
    pr.add_argument("--count", "-n", type=int, default=None)
    pr.add_argument("--backend", "-b", choices=("browser", "protocol", "auto"), default=None)

    pe = sub.add_parser("redeem", help="Redeem promo / trial code")
    pe.add_argument("--accounts", default="data/accounts.txt", help="email|password or cookie")
    pe.add_argument("--codes", default="data/codes.txt", help="one code per line")
    pe.add_argument("--proxy", default=None, help="proxy file, one per line")
    pe.add_argument("--threads", type=int, default=3)
    pe.add_argument("--output", default="data/proof.json")
    pe.add_argument(
        "--success-only",
        action="store_true",
        help="Only success rows from accounts.txt",
    )

    # tuong thich: python canva_tool.py 1 --count 1
    if not argv:
        argv = ["reg"]
    elif argv[0] not in ("reg", "redeem", "-h", "--help"):
        argv = ["reg", *argv]
    args = p.parse_args(argv)
    try:
        if args.cmd == "redeem":
            return cmd_redeem(args)
        return cmd_reg(args)
    except KeyboardInterrupt:
        request_stop("Ctrl+C")
        log.info("Ctrl+C — dừng")
        return 130
    except Exception as e:
        log.exception("%s", e)
        print(f"[-] FAIL: {e}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
