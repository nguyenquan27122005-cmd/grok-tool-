"""Lấy link thanh toán (Stripe) từng gói cho account OpenArt.

login:    POST /api/auth/callback/credentials {csrfToken, email, password, json:true}
checkout: POST /api/stripe/subscription {tier: <số>, billing_interval: year|month}
          → 303 → checkout.stripe.com/c/pay/cs_live_...

Tier = enum số: 1000=Starter, 2000=Plus, 3000=Pro, 3500=Wonder, 4000=Team.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from oareg.log import log
from oareg.paths import ROOT

BASE = "https://openart.ai"

PLANS: dict[str, str] = {
    "starter": "1000",
    "plus": "2000",
    "pro": "3000",
    "wonder": "3500",
    "team": "4000",
}


def parse_accounts(path: Path) -> list[tuple[str, str]]:
    latest: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    if not path.exists():
        return []
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 3 or "@" not in parts[0]:
            continue
        email, password, status = parts[0], parts[1], parts[2]
        if not status.lower().startswith("success"):
            continue
        em = email.lower()
        if em not in latest:
            order.append(em)
        latest[em] = (email, password)
    return [latest[e] for e in order]


def _login(s: requests.Session, email: str, password: str) -> bool:
    csrf = s.get(f"{BASE}/api/auth/csrf", timeout=15).json().get("csrfToken") or ""
    r = s.post(
        f"{BASE}/api/auth/callback/credentials",
        data={"csrfToken": csrf, "email": email, "password": password, "json": "true"},
        timeout=20,
        allow_redirects=True,
    )
    return r.status_code == 200


def checkout_link(s: requests.Session, tier: str, interval: str) -> str:
    last = ""
    for _ in range(3):
        try:
            r = s.post(
                f"{BASE}/api/stripe/subscription",
                data={"tier": tier, "billing_interval": interval},
                headers={"Origin": BASE, "Referer": BASE + "/pricing"},
                timeout=25,
                allow_redirects=False,
            )
            if r.status_code in (302, 303):
                return str(r.headers.get("Location") or "")
            last = f"HTTP {r.status_code} {r.text[:80]}"
            if r.status_code == 400:
                break
        except Exception as e:
            last = str(e)[:100]
        time.sleep(1.5)
    raise RuntimeError(f"checkout fail: {last}")


def run_checkout(
    config: dict[str, Any] | None,
    *,
    plans: list[str],
    interval: str = "month",
    accounts_path: Path | None = None,
    out_path: Path | None = None,
    push_sheet: bool = False,
) -> int:
    config = config or {}
    accounts_path = accounts_path or ROOT / "data/accounts.txt"
    out_path = out_path or ROOT / "data/checkout_links.txt"
    bad = [p for p in plans if p not in PLANS]
    if bad:
        raise RuntimeError(f"Gói không hợp lệ: {', '.join(bad)} — chọn từ {', '.join(PLANS)}")
    interval = "month" if interval == "month" else "year"

    accounts = parse_accounts(accounts_path)
    if not accounts:
        log.warning("Không có account success nào trong %s", accounts_path)
        return 0
    log.info("Checkout %s gói [%s] cho %s account", len(plans), interval, len(accounts))

    s = requests.Session()
    s.trust_env = False
    s.headers.update({"Origin": BASE, "Referer": BASE + "/pricing"})
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}

    rows: list[str] = []
    sheet_rows: list[dict[str, str]] = []
    ok = fail = 0
    for email, password in accounts:
        from oareg.stop import raise_if_stop

        raise_if_stop()
        if not _login(s, email, password):
            log.error("Login FAIL %s", email)
            rows.append(f"{email}|login_failed||")
            fail += 1
            continue
        for plan in plans:
            try:
                url = checkout_link(s, PLANS[plan], interval)
                rows.append(f"{email}|{plan}|{interval}|{url}")
                sheet_rows.append({"email": email, "plan": plan, "interval": interval, "url": url})
                log.info("LINK %s %s(%s): %s", email, plan, interval, url.split("#")[0])
                ok += 1
            except Exception as e:
                rows.append(f"{email}|{plan}|{interval}|error:{str(e)[:80]}")
                log.error("Checkout %s %s FAIL: %s", email, plan, str(e)[:120])
            time.sleep(0.5)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(f"# {time.strftime('%Y-%m-%d %H:%M:%S')} plans={','.join(plans)} interval={interval}\n")
        f.write("\n".join(rows) + "\n")
    log.info("Xong: %s link OK, %s fail — lưu %s", ok, fail, out_path)
    if push_sheet and sheet_rows:
        try:
            from oareg.gsheets import push_checkout_links

            msg = push_checkout_links(sheet_rows)
            log.info("Google Sheet checkout: %s", str(msg)[:160])
        except Exception as e:
            log.error("Google Sheet checkout FAIL: %s — link vẫn nằm trong %s", e, out_path)
    return ok
