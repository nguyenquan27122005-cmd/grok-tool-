#!/usr/bin/env python3
"""Re-import old Grok accounts (accounts.txt added_sub2api) into the new Sub2API."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from grokreg.core.config import load_config
from grokreg.core.runtime import log
from grokreg.browser.chrome import close_browser_handle, open_or_attach_browser
from grokreg.delivery.sub2api_oauth import add_grok_to_sub2api
from grokreg.delivery.sub2api_client import client_from_cfg

ACCOUNTS = ROOT / "data" / "accounts.txt"
PROGRESS = ROOT / "data" / "reimport_progress.jsonl"
NAME_RE = re.compile(r"added_sub2api:\s*(grok free\s+\d+)", re.I)


def parse_old_accounts() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if not ACCOUNTS.exists():
        return out
    for line in ACCOUNTS.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        email, password, status = parts[0], parts[1], "|".join(parts[2:])
        if not email or not password:
            continue
        if "added_sub2api" not in status.lower():
            continue
        m = NAME_RE.search(status)
        name = m.group(1).strip() if m else ""
        out.append((email, password, name))
    # keep last status per email
    seen: dict[str, tuple[str, str, str]] = {}
    for email, password, name in out:
        seen[email.lower()] = (email, password, name)
    return list(seen.values())


def load_done() -> set[str]:
    done: set[str] = set()
    if PROGRESS.exists():
        for line in PROGRESS.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("ok") and rec.get("email"):
                done.add(str(rec["email"]).lower())
    return done


def already_in_sub2api(client, name: str) -> bool:
    if not name:
        return False
    try:
        return client.find_account_by_name(name) is not None
    except Exception as e:
        log.warning("lookup %s failed: %s", name, e)
        return False


def append_progress(rec: dict) -> None:
    with PROGRESS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


async def main() -> int:
    config = load_config()
    config.setdefault("sub2api", {})
    config["sub2api"]["enabled"] = True
    config["sub2api"]["group"] = "grok free"
    config["sub2api"]["group_ids"] = [2]
    config["sub2api"]["run_test"] = False
    # Never reuse leftover Chrome SSO — that stamps the same xAI session onto every name.
    config["sub2api"]["mode"] = "browser_oauth"
    config["sub2api"]["fallback_browser_oauth"] = True
    config["keep_browser_open"] = True
    config["fresh_profile_per_account"] = False

    client = client_from_cfg(config["sub2api"])
    probe = client.test_connection()
    log.info("Sub2API probe: %s", probe)
    if not probe.get("ok"):
        log.error("Cannot login Sub2API — abort")
        return 1

    accounts = parse_old_accounts()
    done = load_done()
    log.info("ledger added_sub2api=%s already_logged=%s", len(accounts), len(done))

    todo = []
    for email, password, name in accounts:
        if email.lower() in done:
            continue
        if name and already_in_sub2api(client, name):
            append_progress({"ok": True, "email": email, "name": name, "skip": "already_in_db"})
            done.add(email.lower())
            continue
        todo.append((email, password, name))
    log.info("to import: %s", len(todo))
    if not todo:
        return 0

    handle = await open_or_attach_browser(config)
    ok = fail = 0
    try:
        for i, (email, password, name) in enumerate(todo, 1):
            log.info("=== [%s/%s] %s name=%s ===", i, len(todo), email, name or "(auto)")
            t0 = time.time()
            try:
                result = await add_grok_to_sub2api(
                    handle.browser,
                    handle.tab,
                    config,
                    email,
                    password,
                    account_name=name or None,
                )
                rec = {
                    "ok": bool(result.ok),
                    "email": email,
                    "name": result.name or name,
                    "stage": result.stage,
                    "message": result.message,
                    "sec": round(time.time() - t0, 1),
                }
            except Exception as e:
                rec = {
                    "ok": False,
                    "email": email,
                    "name": name,
                    "stage": "exception",
                    "message": str(e)[:300],
                    "sec": round(time.time() - t0, 1),
                }
            append_progress(rec)
            if rec["ok"]:
                ok += 1
                log.info("OK %s → %s", email, rec["name"])
            else:
                fail += 1
                log.error("FAIL %s stage=%s %s", email, rec.get("stage"), rec.get("message"))
            await asyncio.sleep(2)
    finally:
        try:
            await close_browser_handle(handle)
        except Exception:
            pass
    log.info("DONE ok=%s fail=%s remaining_approx=%s", ok, fail, max(0, len(todo) - ok - fail))
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
