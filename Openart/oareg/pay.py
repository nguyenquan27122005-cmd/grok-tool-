"""Điền card (CỦA MÌNH) vào trang Stripe Checkout để activate gói OpenArt.

patchright (stealth Chromium) mở link `cs_live_...`, gõ từng ký tự vào field
card (nằm trong iframe elements của Stripe), bấm Subscribe, đọc kết quả:
redirect về openart.ai = ok, error text = declined.

Card nằm trong `data/cards.txt`, mỗi dòng `PAN|MM|YY|CVC[|tên|zip]` — 1 link
ăn 1 card, theo thứ tự. Kết quả → `data/pay_results.txt`.
"""

from __future__ import annotations

import random
import re
import time
from pathlib import Path
from typing import Any

from oareg.log import log
from oareg.paths import ROOT

OUT_PATH = ROOT / "data/pay_results.txt"


def parse_cards(path: Path) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    if not path.exists():
        return cards
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        cards.append(
            {
                "pan": parts[0],
                "exp": f"{parts[1]}/{parts[2]}",
                "cvc": parts[3],
                "name": parts[4] if len(parts) > 4 else "",
                "zip": parts[5] if len(parts) > 5 else "",
            }
        )
    return cards


def _type_slow(loc, text: str, delay: int = 70) -> None:
    for ch in text:
        loc.type(ch, delay=delay + random.randint(-20, 40))


def _card_frame(page):
    for f in page.frames:
        try:
            if f.locator("#cardNumber").count():
                return f
        except Exception:
            continue
    return None


def pay_link(link: str, card: dict[str, str], *, email: str = "", headless: bool = True) -> str:
    """Trả về 'ok' | 'declined: <lý do>' | 'error: <chi tiết>'."""
    from patchright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--window-size=520,900"],
        )
        page = browser.new_page()
        try:
            page.goto(link, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_selector("#email, iframe[src*='js.stripe.com']", timeout=30000)
            time.sleep(random.uniform(1.0, 1.8))

            email_box = page.locator("#email")
            if email_box.count() and not (email_box.input_value() or "").strip() and email:
                email_box.click()
                _type_slow(email_box, email)

            cf = None
            for _ in range(20):
                cf = _card_frame(page)
                if cf:
                    break
                time.sleep(0.5)
            if not cf:
                raise RuntimeError("không thấy iframe cardNumber (page lạ?)")

            cf.locator("#cardNumber").click()
            _type_slow(cf.locator("#cardNumber"), card["pan"])
            time.sleep(random.uniform(0.2, 0.5))
            _type_slow(cf.locator("#cardExpiry"), card["exp"])
            time.sleep(random.uniform(0.15, 0.4))
            _type_slow(cf.locator("#cardCvc"), card["cvc"])

            name_box = page.locator("#billingName")
            if card.get("name") and name_box.count():
                name_box.click()
                _type_slow(name_box, card["name"])
            zip_box = page.locator("#billingPostalCode")
            if card.get("zip") and zip_box.count():
                zip_box.fill(card["zip"])

            btn = page.locator("#submitButton")
            if not btn.count():
                btn = page.get_by_role("button", name=re.compile("subscribe|pay now|start", re.I)).first
            btn.click()
            log.info("[pay] đã submit — chờ kết quả…")

            deadline = time.time() + 90
            while time.time() < deadline:
                if re.search(r"openart\.ai", page.url or ""):
                    log.info("[pay] OK — redirect %s", page.url[:80])
                    return "ok"
                try:
                    err = ""
                    for sel in (".FieldError", "p.FieldError", "[class*='Error']", "#cardErrors"):
                        loc = cf.locator(sel)
                        if loc.count():
                            t = (loc.first.inner_text() or "").strip()
                            if t:
                                err = t
                                break
                    if err:
                        log.warning("[pay] declined: %s", err[:120])
                        return f"declined: {err[:160]}"
                except Exception:
                    pass
                time.sleep(1.0)
            page.screenshot(path=str(ROOT / "data/last_pay_timeout.png"), full_page=True)
            return "error: timeout không thấy redirect/lỗi"
        except Exception as e:
            try:
                page.screenshot(path=str(ROOT / "data/last_pay_fail.png"), full_page=True)
                (ROOT / "data/last_pay_fail.html").write_text(
                    page.content()[:20000], encoding="utf-8", errors="ignore"
                )
            except Exception:
                pass
            return f"error: {str(e)[:160]}"
        finally:
            browser.close()


def run_pay(
    plans: list[str],
    interval: str = "month",
    *,
    accounts_path: Path | None = None,
    cards_path: Path | None = None,
    out_path: Path | None = None,
    limit: int = 0,
    show: bool = False,
) -> int:
    from oareg.checkout import _login, checkout_link, parse_accounts
    from oareg.stop import raise_if_stop

    accounts_path = accounts_path or ROOT / "data/accounts.txt"
    cards_path = cards_path or ROOT / "data/cards.txt"
    out_path = out_path or OUT_PATH
    cards = parse_cards(cards_path)
    if not cards:
        raise RuntimeError(
            f"Không có card trong {cards_path} — thêm dòng PAN|MM|YY|CVC|tên (card CỦA MÌNH)"
        )
    accounts = parse_accounts(accounts_path)
    if limit > 0:
        accounts = accounts[:limit]
    if not accounts:
        log.warning("Không có account success nào trong %s", accounts_path)
        return 0
    log.info("PAY %s gói [%s] × %s account, %s card", len(plans), interval, len(accounts), len(cards))

    s = requests_session()
    rows: list[str] = []
    ok = fail = 0
    card_i = 0
    for email, password in accounts:
        raise_if_stop()
        if card_i >= len(cards):
            log.warning("Hết card — dừng ở %s", email)
            break
        if not _login(s, email, password):
            log.error("Login FAIL %s", email)
            rows.append(f"{email}|login_failed||")
            fail += 1
            continue
        for plan in plans:
            if card_i >= len(cards):
                break
            raise_if_stop()
            card = cards[card_i]
            card_i += 1
            pan_tail = card["pan"][-4:]
            try:
                link = checkout_link(s, _PLAN_IDS[plan], interval)
            except Exception as e:
                link = ""
                log.error("Checkout link %s %s FAIL: %s", email, plan, str(e)[:100])
            if not link:
                rows.append(f"{email}|{plan}|{interval}|no_link|")
                fail += 1
                continue
            log.info("[pay] %s %s(%s) card *%s → %s", email, plan, interval, pan_tail, link.split("#")[0][:70])
            res = pay_link(link, card, email=email, headless=not show)
            rows.append(f"{email}|{plan}|{interval}|{res}|*{pan_tail}")
            if res == "ok":
                ok += 1
            else:
                fail += 1
            time.sleep(random.uniform(1.5, 3.0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(f"# {time.strftime('%Y-%m-%d %H:%M:%S')} plans={','.join(plans)} interval={interval}\n")
        f.write("\n".join(rows) + "\n")
    log.info("Xong: %s ok, %s fail — %s", ok, fail, out_path)
    return ok


_PLAN_IDS = {"starter": "1000", "plus": "2000", "pro": "3000", "wonder": "3500", "team": "4000"}


def requests_session():
    import requests

    s = requests.Session()
    s.trust_env = False
    s.headers.update({"Origin": "https://openart.ai", "Referer": "https://openart.ai/pricing"})
    return s
