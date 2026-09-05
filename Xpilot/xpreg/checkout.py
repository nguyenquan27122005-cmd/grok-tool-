"""Lấy link thanh toán (Stripe checkout) từng gói cho từng account X-Pilot.

login:  POST https://server.x-pilot.ai/auth/sign_in {login, password}
        → data.token (JWT 7 ngày)
pay:    POST /api/payments/create-checkout-session {product_id: <số 5..12>}
        → data.checkoutUrl = https://checkout.stripe.com/c/pay/cs_live_...
Link sống ~24h (Stripe session), trả tự do không bắt buộc thanh toán.

product_id (bảng trong usePricing chunk, 2026-09-05):
  5 creator/monthly $19 · 7 creator/year $15
  6 pro/monthly     $49 · 8 pro/year     $39
  9 ultra/monthly  $129 · 10 ultra/year $103
 11 business/monthly$159 · 12 business/year$127
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from xpreg.log import log
from xpreg.paths import ROOT
from xpreg.stop import StopRequested, raise_if_stop

BASE = "https://server.x-pilot.ai"

PLANS: dict[str, dict[str, int]] = {
    "creator": {"monthly": 5, "yearly": 7},
    "pro": {"monthly": 6, "yearly": 8},
    "ultra": {"monthly": 9, "yearly": 10},
    "business": {"monthly": 11, "yearly": 12},
}


def _session(config: dict[str, Any]):
    from xpreg.protocol import _session

    return _session(config)


def _sign_in(s, email: str, password: str) -> str:
    from xpreg.protocol import sign_in

    out = sign_in(s, email=email, password=password)
    if out.get("ok"):
        return str(out.get("token") or "")
    return ""


def checkout_link(s, token: str, product_id: int) -> str:
    last = ""
    for _attempt in range(3):
        try:
            r = s.post(
                f"{BASE}/api/payments/create-checkout-session",
                json={"product_id": product_id},
                headers={"Authorization": f"Bearer {token}"},
                timeout=25,
            )
            if r.status_code == 200:
                url = ((r.json() or {}).get("data") or {}).get("checkoutUrl") or ""
                if url:
                    return url
                last = "checkout không trả checkoutUrl"
            else:
                last = f"HTTP {r.status_code} {r.text[:120]}"
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
        token = _sign_in(s, email, password)
        if not token:
            log.error("Login FAIL %s — bỏ qua", email)
            rows.append(f"{email}|login_failed||")
            fail += 1
            continue
        for plan in plans:
            pid = PLANS[plan][interval]
            try:
                url = checkout_link(s, token, pid)
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
            from xpreg.gsheets import push_checkout_links

            msg = push_checkout_links(sheet_rows)
            log.info("Google Sheet checkout: %s", str(msg)[:160])
        except Exception as e:
            log.error("Google Sheet checkout FAIL: %s — link vẫn nằm trong %s", e, out_path)
    return ok
