#!/usr/bin/env python3
"""Login 3 Canva accs and check if TMM3FREE really applied Pro/trial."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from canreg.config import load_config
from canreg.log import log
from canreg.paths import DATA
from canreg.redeem import Acc, _login_browser, attach_hotmail_tokens

EMAILS = [
    "FeltonChessman9124+1@hotmail.com",
    "FeltonChessman9124+2@hotmail.com",
    "XzavierHelgerson726225@hotmail.com",
]
PASSWORD = "Canva@2026!Safe"
CHECK_URLS = (
    "https://www.canva.com/settings/billing",
    "https://www.canva.com/settings/",
    "https://www.canva.com/_ajax/subscription",
    "https://www.canva.com/_ajax/csrf3/subscription",
    "https://www.canva.com/redeem/",
)

PRO_RE = re.compile(
    r"canva pro|you.?re a pro|pro member|pro plan|pro trial|trial ends|expires|expiry|"
    r"renews on|next billing|education|teams",
    re.I,
)
FAIL_RE = re.compile(
    r"couldn.?t redeem|cannot redeem|can.?t redeem|unable to redeem|"
    r"invalid code|already (used|redeemed)|we couldn",
    re.I,
)
FREE_RE = re.compile(r"upgrade to pro|go pro|try pro|canva free|you.?re on the free", re.I)
DATE_RE = re.compile(
    r"(?:ends?|expires?|renews?|until|through)\s*(?:on\s*)?"
    r"([A-Z][a-z]+ \d{1,2},? \d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})",
    re.I,
)


def _snip(text: str, n: int = 700) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


async def inspect_one(config: dict, acc: Acc) -> dict:
    from canreg.browser import _body, _js, _sleep, close_browser, open_browser

    out = {
        "email": acc.email,
        "login": "",
        "plan": "unknown",
        "real_redeem": False,
        "evidence": "",
        "expire_hint": "",
        "pages": {},
    }
    browser = None
    try:
        browser, tab = await open_browser(config, wipe_old=True)
        how = await _login_browser(tab, acc, config)
        out["login"] = how
        log.info("%s login=%s", acc.email, how)
        if how not in ("ok", "already"):
            out["evidence"] = f"login failed: {how}"
            return out

        blobs: list[str] = []
        for url in CHECK_URLS:
            try:
                await tab.go_to(url)
                await _sleep(2.0)
                href = str(await _js(tab, "location.href") or "")
                body = await _body(tab)
                text = _snip(body, 2500)
                out["pages"][url.split(".com", 1)[-1]] = {
                    "href": href,
                    "len": len(body or ""),
                    "pro": bool(PRO_RE.search(text)),
                    "free": bool(FREE_RE.search(text)),
                    "fail": bool(FAIL_RE.search(text)),
                    "snip": text[:280],
                }
                blobs.append(text)
                m = DATE_RE.search(text)
                if m and not out["expire_hint"]:
                    out["expire_hint"] = m.group(0)
            except Exception as e:
                out["pages"][url] = {"error": str(e)[:160]}

        all_txt = "\n".join(blobs)
        if FAIL_RE.search(all_txt) and not PRO_RE.search(all_txt):
            out["plan"] = "free"
            out["real_redeem"] = False
            out["evidence"] = "Canva báo không redeem được / không thấy Pro"
        elif PRO_RE.search(all_txt) and not FREE_RE.search(all_txt):
            out["plan"] = "pro_or_trial"
            out["real_redeem"] = True
            out["evidence"] = "Trang billing/settings có chữ Pro/trial"
        elif FREE_RE.search(all_txt):
            out["plan"] = "free"
            out["real_redeem"] = False
            out["evidence"] = "Trang hiện Free / Upgrade to Pro"
        elif PRO_RE.search(all_txt):
            out["plan"] = "maybe_pro"
            out["real_redeem"] = True
            out["evidence"] = "Có chữ Pro nhưng vẫn lẫn hint Free — cần xem tay"
        else:
            out["plan"] = "unknown"
            out["evidence"] = "Không đọc được gói từ trang"
        return out
    except Exception as e:
        out["evidence"] = str(e)[:200]
        return out
    finally:
        if browser is not None:
            try:
                await close_browser(browser)
            except Exception:
                pass


async def main() -> int:
    config = load_config()
    config["keep_browser_open"] = False
    results = []
    for email in EMAILS:
        acc = Acc(email=email, password=PASSWORD)
        attach_hotmail_tokens(acc)
        log.info("=== check %s refresh=%s ===", email, bool(acc.refresh))
        rec = await inspect_one(config, acc)
        results.append(rec)
        print(
            json.dumps(
                {k: rec[k] for k in ("email", "login", "plan", "real_redeem", "expire_hint", "evidence")},
                ensure_ascii=False,
            )
        )
    dest = DATA / "redeem_verify.json"
    dest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
