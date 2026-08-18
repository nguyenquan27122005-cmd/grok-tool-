"""Auto-split from main.py — modular package."""
from __future__ import annotations

import argparse
import asyncio
import email as email_lib
import imaplib
import json
import logging
import os
import random
import re
import string
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions

import grokreg.browser.anti_flag as af
from grokreg.mail.tmail_wibu import TmailWibuProvider
import grokreg.mail.temp_mail_router as tmr
import grokreg.browser.chrome_cleanup as chrome_clean
import grokreg.core.style_log as slog
from grokreg.core.stop_control import (
    StopRequested,
    clear_stop,
    interruptible_sleep,
    is_stop_requested,
    raise_if_stop,
    request_stop,
    sleep_interruptible,
    start_esc_listener,
    stop_reason,
)

from grokreg.core.runtime import (
    ROOT,
    DATA_DIR,
    CONFIG_PATH,
    log,
    MS_CLIENT_IDS,
    FIRST_NAMES,
    LAST_NAMES,
    RATE_LIMIT_PATH,
)


from grokreg.core.config import load_config
from grokreg.core.cleanup import kill_old_runs
from grokreg.reg.flow import register_one

def parse_provider_choice(raw: str | None) -> Optional[str]:
    """Map user input → provider mode | None."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("1", "hotmail", "outlook", "ms", "h"):
        return "hotmail"
    if s in ("0", "temp", "tempmail", "auto_temp", "failover", "smart", "s"):
        return "auto_temp"
    if s in ("2", "azpopmail", "azpop", "a"):
        return "azpopmail"
    if s in (
        "3",
        "tmail_wibu",
        "tmailwibu",
        "wibu",
        "wibucrypto",
        "tmail",
        "t",
    ):
        return "tmail_wibu"
    if s in ("4", "mailtm", "mail.tm", "m"):
        return "mailtm"
    return None


def pick_email_provider(cli_choice: str | None = None) -> str:
    """
    User picks provider.
      CLI:  python main.py 0 | 1 | 2 | 3
            0 = auto_temp (azpop↔wibu failover)
      Menu: interactive if no CLI choice
    """
    chosen = parse_provider_choice(cli_choice)
    if chosen:
        return chosen

    # Non-interactive (piped / no TTY): default auto_temp for runners
    if not sys.stdin.isatty():
        # overnight/batch pass explicit arg; if missing → auto_temp
        return "auto_temp"

    print()
    print("=" * 52)
    print("  GROK REGISTER — chọn email")
    print("=" * 52)
    print("  0) Temp smart  (azpop ↔ wibu, tự đổi khi lag)  [khuyên dùng]")
    print("  1) Hotmail     (hotmails.txt)")
    print("  2) Temp only   azpopmail.com")
    print("  3) Temp only   tmail.wibucrypto.pro")
    print("=" * 52)
    labels = {
        "auto_temp": "Temp smart (azpop↔wibu failover)",
        "hotmail": "Hotmail",
        "azpopmail": "Temp only azpopmail.com",
        "tmail_wibu": "Temp only tmail.wibucrypto.pro",
        "mailtm": "Mail.tm",
    }
    while True:
        try:
            ans = input("Chọn [0/1/2/3] (Enter=0): ").strip() or "0"
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit("Đã hủy.")
        chosen = parse_provider_choice(ans)
        if chosen in labels:
            print(f"→ Dùng {labels[chosen]}\n")
            return chosen
        print("  Chỉ nhập 0, 1, 2 hoặc 3.")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Grok register: 0=auto_temp failover | 1=Hotmail | "
            "2=azpopmail | 3=tmail.wibucrypto.pro"
        ),
    )
    p.add_argument(
        "choice",
        nargs="?",
        default=None,
        help="0 auto_temp | 1 hotmail | 2 azpop | 3 wibu",
    )
    p.add_argument(
        "--provider",
        "-p",
        dest="provider",
        default=None,
        help="hotmail | auto_temp | azpopmail | tmail_wibu | mailtm",
    )
    p.add_argument(
        "--count",
        "-n",
        type=int,
        default=None,
        help=(
            "How many accounts this run (default: config batch_count or 1). "
            "Use 0 = run forever until data/STOP or Ctrl+C"
        ),
    )
    p.add_argument(
        "--backend",
        "-b",
        dest="backend",
        default=None,
        choices=("browser", "protocol", "github", "auto"),
        help=(
            "browser=Chrome UI | github=HTTP GitHub 0 Chrome (~30s, solver :5072) "
            "| protocol=HTTP + Castle (Chrome mint) | auto=github rồi fallback Chrome"
        ),
    )
    return p


async def main(argv: list[str] | None = None) -> None:  # noqa: C901
    args = build_arg_parser().parse_args(argv)
    cli = args.provider or args.choice
    provider = pick_email_provider(cli)

    # Parallel stress workers set GROK_SKIP_KILL_OLD=1 so siblings are not killed
    if os.environ.get("GROK_SKIP_KILL_OLD", "").strip() not in ("1", "true", "yes"):
        # Only kill orphaned Temp Chrome — never kill live CDP on our profile port
        kill_old_runs(also_chrome=True, keep_pid=os.getpid())
    else:
        log.info("GROK_SKIP_KILL_OLD=1 — skip killing other main.py / chrome")

    config = load_config()
    # User choice always wins — ignore config auto
    config["email_provider"] = provider
    # reg_backend: browser (default) | protocol | auto
    # CLI override: --backend protocol
    if getattr(args, "backend", None):
        config["reg_backend"] = str(args.backend).strip().lower()

    backend_now = str(
        config.get("reg_backend")
        or (config.get("protocol") or {}).get("mode")
        or "browser"
    ).strip().lower()
    if backend_now in ("protocol", "auto", "http", "pure_http", "github", "castle"):
        try:
            from services.solver_manager import start_async

            start_async(config)
            log.info("Turnstile solver: auto-start background (:5072)")
        except Exception as e:
            log.debug("solver auto-start: %s", e)

    # Optional per-worker overrides (stress_test.py / multi-instance)
    if os.environ.get("GROK_CHROME_PORT", "").strip():
        config["chrome_debug_port"] = int(os.environ["GROK_CHROME_PORT"])
    if os.environ.get("GROK_CHROME_PROFILE", "").strip():
        config["chrome_user_data_dir"] = os.environ["GROK_CHROME_PROFILE"]
        config["fresh_profile_per_account"] = False
    if os.environ.get("GROK_SUB2API", "").strip().lower() in ("0", "false", "no", "off"):
        config.setdefault("sub2api", {})
        config["sub2api"]["enabled"] = False
        log.info("GROK_SUB2API=0 — Sub2API import disabled for this run")

    # Durable Sub2API delivery worker (competitor pattern: reg ≠ upload)
    try:
        from grokreg.delivery.delivery_retry import ensure_worker, process_queue_once, queue_stats

        ensure_worker(config)
        drained = process_queue_once(config, limit=5)
        stats = queue_stats()
        if drained or stats.get("pending"):
            log.info(
                "delivery queue: drained=%s pending=%s done=%s failed=%s",
                drained,
                stats.get("pending"),
                stats.get("done"),
                stats.get("failed"),
            )
    except Exception as e:
        log.debug("delivery worker init: %s", e)

    # ESC / STOP control — clear leftover STOP, start keyboard listener
    clear_stop()
    start_esc_listener()

    # --count 0 (or negative) = loop until STOP file / ESC / Ctrl+C
    raw_count = args.count
    if raw_count is None:
        batch = int(config.get("batch_count") or 1)
    else:
        batch = int(raw_count)
    until_stop = batch <= 0
    if not until_stop:
        batch = max(1, batch)
    dmin = float(config.get("inter_success_delay_min") or 45)
    dmax = float(config.get("inter_success_delay_max") or 90)
    threads = max(1, int(os.environ.get("GROK_THREADS") or config.get("threads") or 1))

    stop_file = ROOT / "data" / "STOP"

    log.info(
        "User selected email_provider=%s | batch=%s until_stop=%s | fresh_profile=%s | humanize=%s",
        provider,
        "∞" if until_stop else batch,
        until_stop,
        config.get("fresh_profile_per_account", True),
        config.get("humanize", True),
    )

    # Styled banner (display only)
    slog.banner(999 if until_stop else batch, threads=threads)
    slog.api_info(
        "⌨️",
        "Nhấn ESC = DỪNG ngay mọi việc  |  Ctrl+C cũng được  |  menu [2] ghi data/STOP",
    )
    if until_stop:
        slog.api_info(
            "♾️",
            "Chạy liên tục đến khi ESC / Ctrl+C / data/STOP",
        )

    ok_n = 0
    i = 0
    try:
        while True:
            if is_stop_requested():
                slog.api_info(
                    "🛑",
                    f"Dừng theo lệnh ({stop_reason() or 'STOP'}) — {i} lượt, ok={ok_n}",
                )
                break

            i += 1
            if not until_stop and i > batch:
                break
            # STOP file / ESC between accounts
            if is_stop_requested() or stop_file.exists():
                slog.api_info(
                    "🛑",
                    f"Gặp STOP/ESC — dừng sau {i - 1} lượt (ok={ok_n})",
                )
                try:
                    if stop_file.exists():
                        stop_file.unlink()
                except Exception:
                    pass
                break

            total_disp = 999 if until_stop else batch
            log.info(
                "======== ACCOUNT %s / %s ========",
                i,
                "∞" if until_stop else batch,
            )
            slog.set_task(task_id=i, cur=i, total=total_disp)
            try:
                raise_if_stop()
                backend = str(
                    config.get("reg_backend")
                    or (config.get("protocol") or {}).get("mode")
                    or "browser"
                ).strip().lower()
                if backend in ("github", "http", "pure_http"):
                    slog.api_info("⚡", "Backend GITHUB (HTTP thuần — 0 Chrome)")
                    from grokreg.protocol.worker import register_one_github

                    def _run_github():
                        return register_one_github(config)

                    result = await asyncio.to_thread(_run_github)
                    status = result.status
                    if result.ok:
                        slog.api_ok(
                            f"GitHub-HTTP OK {result.email} in {result.duration_sec:.1f}s → {status}"
                        )
                elif backend in ("protocol", "castle"):
                    slog.api_info("⚡", "Backend PROTOCOL (HTTP + Castle Chrome)")
                    from grokreg.protocol.worker import register_one_protocol

                    def _run_proto():
                        return register_one_protocol(config, castle=True)

                    result = await asyncio.to_thread(_run_proto)
                    status = result.status
                    if result.ok:
                        slog.api_ok(
                            f"Protocol OK {result.email} in {result.duration_sec:.1f}s → {status}"
                        )
                elif backend == "auto":
                    slog.api_info("⚡", "Backend AUTO — thử HTTP GitHub trước")
                    from grokreg.protocol.worker import register_one_github

                    result = await asyncio.to_thread(register_one_github, config)
                    if result.ok and (
                        result.status.startswith("added_sub2api")
                        or result.status == "success"
                        or result.status.startswith("success_sub2api")
                    ):
                        status = result.status
                        slog.api_ok(
                            f"Protocol OK {result.email} in {result.duration_sec:.1f}s"
                        )
                    else:
                        log.warning(
                            "protocol failed (%s) — fallback browser",
                            result.status,
                        )
                        slog.api_info("↩️", "Protocol fail — fallback browser UI")
                        status = await register_one(config)
                else:
                    status = await register_one(config)
            except StopRequested as e:
                status = "stopped"
                slog.api_info("🛑", f"ESC/STOP giữa reg — {e.reason}")
            except KeyboardInterrupt:
                request_stop("Ctrl+C")
                raise
            except Exception as e:
                log.exception("register_one crashed: %s", e)
                slog.api_err(f"register_one crashed: {e}")
                status = f"error:{e}"
            st = str(status or "")
            if st == "stopped":
                slog.api_info("🛑", f"Đã dừng (ok={ok_n} / lượt={i})")
                break
            successish = (
                st == "success"
                or st.startswith("added_sub2api")
                or st.startswith("success_sub2api")
                or st.startswith("added_sub2api_untested")
            )
            if successish:
                ok_n += 1
            elif st.startswith("error:"):
                slog.api_err(st)

            # more work?
            more = until_stop or i < batch
            if more:
                if is_stop_requested() or stop_file.exists():
                    slog.api_info("🛑", "Gặp STOP/ESC — dừng ngay")
                    try:
                        if stop_file.exists():
                            stop_file.unlink()
                    except Exception:
                        pass
                    break
                if successish:
                    pause = af.inter_account_cooldown(dmin, dmax)
                    log.info(
                        "Inter-success cooldown %.0fs (random %.0f–%.0f) before next account... (ESC=dừng)",
                        pause,
                        dmin,
                        dmax,
                    )
                else:
                    pause = af.human_delay(max(20.0, dmin * 0.5), dmax)
                    log.info(
                        "Inter-attempt pause %.0fs after non-success... (ESC=dừng)",
                        pause,
                    )
                try:
                    await interruptible_sleep(pause)
                except StopRequested:
                    slog.api_info("🛑", "ESC trong lúc chờ — dừng batch")
                    break
    except StopRequested as e:
        slog.api_info("🛑", f"ESC/STOP — dừng (đã chạy {i} lượt, ok={ok_n}) [{e.reason}]")
    except KeyboardInterrupt:
        request_stop("Ctrl+C", write_file=True)
        slog.api_info("🛑", f"Ctrl+C — dừng (đã chạy {i} lượt, ok={ok_n})")

    if until_stop:
        log.info("Loop done: %s success-ish / %s attempts", ok_n, i)
        slog.api_ok(f"Kết thúc loop: {ok_n} OK / {i} lượt")
    else:
        log.info("Batch done: %s/%s success-ish", ok_n, batch)


if __name__ == "__main__":
    asyncio.run(main())


