"""Lấy link thanh toán (Stripe checkout) từng gói cho từng account SciSpace.

login:  POST /api/auth/login  {auth_type:"auth_login", auth_payload:{email,password}}
pay:    POST /api/stripe/checkout/session
        {line_items:[{price:<price_id>,quantity:1}],hook:null,is_free_trial:false}
→ 200 {"id","url":"https://pay.scispace.com/c/pay/cs_live_..."}
Link sống ~24h (Stripe session), trả tự do không bắt buộc thanh toán.

Price ids lấy cứng từ pricing page (__NEXT_DATA__, 2026-09-05).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from curl_cffi import requests as creq

from ssreg.log import log
from ssreg.paths import ROOT
from ssreg.stop import StopRequested, raise_if_stop

BASE = "https://scispace.com"

PLANS: dict[str, dict[str, str]] = {
    "premium": {
        "monthly": "price_1Np8J9FlY1I0ZNrq92cTeWqc",
        "yearly": "price_1O3xBZFlY1I0ZNrqTC0qzHIG",
    },
    "advanced": {
        "monthly": "price_1QrgYfFlY1I0ZNrqlYzzo4w4",
        "yearly": "price_1Qrgb9FlY1I0ZNrq6YDX7cKG",
    },
    "max": {
        "monthly": "price_1TSA4SFlY1I0ZNrq6ACQOQTW",
        "yearly": "price_1TSBxaFlY1I0ZNrq4Oa2LE7h",
    },
    # Team plans tính theo user, tối thiểu 2 users
    "team": {
        "monthly": "price_1TMSq1FlY1I0ZNrq5ILALzYu",
        "yearly": "price_1TMSrjFlY1I0ZNrqYUKZCUzx",
    },
    "team_advanced": {
        "monthly": "price_1TMStbFlY1I0ZNrqe170iXJe",
        "yearly": "price_1TMSuHFlY1I0ZNrq5v611QQ5",
    },
    "team_max": {
        "monthly": "price_1TMSy7FlY1I0ZNrqgeXyhCi6",
        "yearly": "price_1TMSynFlY1I0ZNrqazsLr7Zo",
    },
}


def _session(config: dict[str, Any]):
    s = creq.Session(impersonate="chrome131")
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update(
        {
            "Origin": BASE,
            "Referer": BASE + "/pricing",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
    )
    return s


def _login(s, email: str, password: str) -> bool:
    try:
        s.get(BASE + "/pricing", timeout=25)
        r = s.post(
            f"{BASE}/api/auth/login",
            json={"auth_type": "auth_login", "auth_payload": {"email": email, "password": password}},
            timeout=25,
        )
        return r.status_code == 200 and '"user"' in r.text
    except Exception as e:
        log.warning("login %s: %s", email, str(e)[:100])
        return False


def checkout_link(s, price_id: str, quantity: int = 1) -> str:
    last = ""
    for attempt in range(1, 4):
        try:
            r = s.post(
                f"{BASE}/api/stripe/checkout/session",
                json={
                    "line_items": [{"price": price_id, "quantity": quantity}],
                    "hook": None,
                    "is_free_trial": False,
                },
                timeout=25,
            )
            if r.status_code == 200:
                url = (r.json() or {}).get("url") or ""
                if url:
                    return url
                last = "checkout không trả url"
            else:
                last = f"HTTP {r.status_code}"
                if r.status_code != 500:
                    break  # lỗi ngoài 500 (auth/param) — retry vô ích
        except Exception as e:
            last = str(e)[:100]
        time.sleep(1.5)
    raise RuntimeError(f"checkout fail: {last}")


def parse_accounts(path: Path) -> list[tuple[str, str]]:
    """accounts.txt: email|password|status|ts → các dòng success (mới nhất theo email)."""
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


def run_checkout(
    config: dict[str, Any],
    *,
    plans: list[str],
    interval: str = "monthly",
    accounts_path: Path | None = None,
    out_path: Path | None = None,
    push_sheet: bool = False,
) -> int:
    accounts_path = accounts_path or ROOT / "data/accounts.txt"
    out_path = out_path or ROOT / "data/checkout_links.txt"
    bad = [p for p in plans if p not in PLANS]
    if bad:
        raise RuntimeError(f"Gói không hợp lệ: {', '.join(bad)} — chọn từ {', '.join(PLANS)}")
    if interval not in ("monthly", "yearly"):
        interval = "monthly"

    accounts = parse_accounts(accounts_path)
    if not accounts:
        log.warning("Không có account success nào trong %s", accounts_path)
        return 0
    log.info("Checkout %s gói [%s] cho %s account (%s)", len(plans), interval, len(accounts), ", ".join(plans))

    s = _session(config)
    rows: list[str] = []
    sheet_rows: list[dict[str, str]] = []
    ok = fail = 0
    for email, password in accounts:
        raise_if_stop()
        if not _login(s, email, password):
            log.error("Login FAIL %s — bỏ qua", email)
            rows.append(f"{email}|login_failed||")
            fail += 1
            continue
        for plan in plans:
            price = PLANS[plan][interval]
            qty = 2 if plan.startswith("team_") else 1
            try:
                url = checkout_link(s, price, qty)
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
            from ssreg.gsheets import push_checkout_links

            msg = push_checkout_links(sheet_rows)
            log.info("Google Sheet checkout: %s", str(msg)[:160])
        except Exception as e:
            log.error("Google Sheet checkout FAIL: %s — link vẫn nằm trong %s", e, out_path)
    return ok
