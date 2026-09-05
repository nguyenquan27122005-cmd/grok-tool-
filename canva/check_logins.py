"""Check hàng loạt acc Canva còn log vào được không (mk hoặc OTP qua tmail).

Chạy: venv python check_logins.py [threads]
Danh sách: data/check_list.txt — mỗi dòng email|password (thiếu mk = Canva@2026!Safe)
Kết quả: data/login_check.txt + tổng hợp stdout
Status: OK_MK (login bằng mk) · OK_OTP (login bằng OTP, kèm gói) ·
        SAI_MK · BI_CHAN (Canva chặn email — RRS) ·
        HONG_OTP (OTP không đến — không xác nhận được) · LOI
"""

import asyncio
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, r"D:\grok_tool\canva")
sys.path.insert(0, r"D:\grok_tool\grok_tool")

from canreg.browser import (
    _body,
    _click,
    _click_continue,
    _fill,
    _fill_otp,
    _js,
    _logged_in,
    _sleep,
    _wait_cf,
    _wait_stage,
    close_browser,
    open_browser,
)
from canreg.config import load_config
from canreg.log import log
from canreg.mail import wait_canva_mail
from canreg.offers import offer_from_page
from canreg.redeem import FILL_PROMO_JS

DEFAULT_PW = "Canva@2026!Safe"
LIST_FILE = Path(__file__).resolve().parent / "data" / "check_list.txt"
OUT_FILE = Path(__file__).resolve().parent / "data" / "login_check.txt"


def load_accounts(path: Path | None = None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for ln in (path or LIST_FILE).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("|")
        email = parts[0].strip()
        pw = parts[1].strip() if len(parts) > 1 and parts[1].strip() else DEFAULT_PW
        if email:
            rows.append((email, pw))
    return rows


def _looks_otp_screen(low: str) -> bool:
    for marker in (
        "check your email",
        "we sent",
        "enter the code",
        "6-digit",
        "verification code",
        "log in code",
        "magic link",
        "enter code",
    ):
        if marker in low:
            return True
    return False


def open_tmail_mailbox(email: str, config: dict) -> tuple[Any, dict, str]:
    """Mở lại hộp tmail ĐÃ CÓ theo địa chỉ: gọi create đúng tên user@domain
    qua Livewire (hòm không cần mk). Trả về (tmail, extra, page_email) — giữ
    nguyên instance provider vì cookie nằm trong requests.Session của nó."""
    from grokreg.mail.tmail_wibu import TmailWibuProvider

    tmail = TmailWibuProvider(dict(config.get("tmail_wibu") or {}))
    user, _, domain = email.partition("@")
    _page, csrf, _app, actions = tmail.handshake()
    tmail._livewire_post(
        "frontend.actions",
        actions["fingerprint"],
        actions["serverMemo"],
        [
            {"type": "syncInput", "payload": {"id": "u", "name": "user", "value": user}},
            {"type": "syncInput", "payload": {"id": "d", "name": "domain", "value": domain}},
            {
                "type": "callMethod",
                "payload": {
                    "id": f"c{int(time.time() * 1000)}",
                    "method": "create",
                    "params": [],
                },
            },
        ],
        csrf,
    )
    # re-handshake để cookie + checksum khớp hòm vừa mở (như create_mailbox)
    page_email2, csrf2, app2, actions2 = tmail.handshake()
    extra = {
        "base_url": tmail.base,
        "csrf": csrf2,
        "cookies": tmail._http.cookies.get_dict(),
        "app_fingerprint": app2.get("fingerprint") or {},
        "app_server_memo": app2.get("serverMemo") or {},
        "actions_fingerprint": actions2.get("fingerprint") or {},
        "actions_server_memo": actions2.get("serverMemo") or {},
    }
    return tmail, extra, str(page_email2 or "")


def fetch_otp(tmail: Any, session: SimpleNamespace, config: dict) -> str:
    """Lấy OTP login Canva từ hộp tmail đã mở (bỏ qua mã reg cũ theo subject)."""
    try:
        tmail._restore_cookies(dict((session.extra or {}).get("cookies") or {}))
    except Exception:  # noqa: BLE001
        pass
    proof = wait_canva_mail(
        session,
        config,
        tmail=tmail,
        timeout=75,
        require_login_subject=True,
    )
    return str((proof or {}).get("code") or "")


def check_one(config: dict, email: str, password: str) -> tuple[str, str]:
    """Trả về (status, detail)."""

    async def _run() -> tuple[str, str]:
        # mở hộp tmail TRƯỚC khi login — OTP về đúng hòm mình đang giữ
        try:
            tmail, extra, shown = await asyncio.to_thread(open_tmail_mailbox, email, config)
        except Exception as e:  # noqa: BLE001
            return "HONG_OTP", f"mở hộp tmail lỗi: {e}"[:100]
        if shown.lower() != email.lower():
            return "HONG_OTP", f"hộp không mở theo địa chỉ (site hiện {shown or '?'})"
        session = SimpleNamespace(address=email, provider="tmail_wibu", extra=extra)

        browser, tab = await open_browser(config)
        try:
            await tab.go_to("https://www.canva.com/login")
            await _sleep(1.8)
            await _wait_cf(tab)
            clicked = await _click(tab, "continue with email", "log in with email")
            if clicked:
                await _wait_stage(tab, not_in=("landing",), seconds=8)
            n = 0
            for _ in range(4):
                n = await _fill(tab, "email", email)
                if n:
                    break
                await _sleep(1.0)
            if not n:
                return "LOI", "không điền được email (trang không render)"
            await _sleep(0.4)
            await _click_continue(tab)

            def _rrs(low: str) -> str:
                m = re.search(r"rrs[-–‑][a-z0-9]+", low)
                return m.group(0).upper().replace("–", "-").replace("‑", "-") if m else "?"

            # đợi: hỏi mk / đi thẳng OTP / bị chặn luôn
            has_pw = False
            on_otp = False
            for _ in range(10):
                await _sleep(1.5)
                low = (await _body(tab) or "").replace("\n", " ").lower()
                if "enter password" in low or ("forgot password" in low and "password" in low):
                    has_pw = True
                    break
                if "be used on canva" in low:
                    return "BI_CHAN", f"Canva chặn email này (mã {_rrs(low)}) — không gửi OTP"
                if _looks_otp_screen(low):
                    on_otp = True
                    break

            if has_pw:
                raw = await _js(tab, FILL_PROMO_JS.replace("%VAL%", json.dumps(password)))
                if not str(raw or "").startswith(("ok", "1")):
                    return "LOI", f"không điền được mk ({raw})"
                await _sleep(0.3)
                await _click_continue(tab)
                for _ in range(8):
                    await _sleep(1.5)
                    url = str(await _js(tab, "location.href") or "")
                    body = await _body(tab) or ""
                    low = body.replace("\n", " ").lower()
                    if _logged_in(url, body):
                        return "OK_MK", ""
                    if "incorrect" in low or "wrong" in low or "couldn't log you in" in low:
                        bad = [ln.strip() for ln in body.splitlines() if "incorrect" in ln.lower() or "wrong" in ln.lower()]
                        return "SAI_MK", (bad[0][:120] if bad else "Canva báo mk sai")
                url = str(await _js(tab, "location.href") or "")
                if _logged_in(url, await _body(tab) or ""):
                    return "OK_MK", ""
                return "LOI", f"mk xong không vào được — url={url[:70]}"

            if not on_otp:
                url = str(await _js(tab, "location.href") or "")
                return "LOI", f"không ra màn OTP/mk — url={url[:70]}"

            # passwordless — nhận OTP từ tmail rồi login; trong lúc chờ vẫn soi
            # màn hình vì lỗi chặn RRS có khi render chậm hơn 10s
            task = asyncio.ensure_future(asyncio.to_thread(fetch_otp, tmail, session, config))
            chan = ""
            for _ in range(28):  # ~84s ≥ timeout 75s của fetch
                await _sleep(3)
                low = (await _body(tab) or "").replace("\n", " ").lower()
                if "be used on canva" in low:
                    chan = f"Canva chặn email này (mã {_rrs(low)}) — không gửi OTP"
                    break
                if task.done():
                    break
            if chan:
                return "BI_CHAN", chan
            code = str(task.result()) if task.done() else ""
            if not code:
                return "HONG_OTP", "OTP không về hộp tmail (75s)"
            put = await _fill_otp(tab, code)
            nxt = await _wait_stage(tab, not_in=("otp",), seconds=20)
            url = str(await _js(tab, "location.href") or "")
            body = await _body(tab) or ""
            if nxt == "otp" or not _logged_in(url, body):
                # thử lần nữa: mã có thể là mã cũ — đợi mail mới
                code2 = await asyncio.to_thread(fetch_otp, tmail, session, config)
                if code2 and code2 != code:
                    await _fill_otp(tab, code2)
                    nxt = await _wait_stage(tab, not_in=("otp",), seconds=20)
                    url = str(await _js(tab, "location.href") or "")
                    body = await _body(tab) or ""
            if not _logged_in(url, body):
                return "HONG_OTP", f"OTP nhập xong không vào được — url={url[:70]}"

            # login OK — đọc gói ở /settings/billing
            plan = ""
            try:
                await tab.go_to("https://www.canva.com/settings/billing")
                await _sleep(1.5)
                cur = str(await _js(tab, "location.href") or "")
                offer = offer_from_page(cur, await _body(tab) or "")
                plan = str(offer.get("summary") or "")
            except Exception as e:  # noqa: BLE001
                plan = f"offer_err:{e}"[:60]
            return "OK_OTP", plan
        except Exception as e:  # noqa: BLE001
            return "LOI", f"exception: {e}"[:140]
        finally:
            try:
                await close_browser(
                    browser,
                    port=(config.get("chrome_debug_port") if config.get("chrome_parallel") else None),
                )
            except Exception:
                pass

    return asyncio.run(_run())


def main() -> int:
    threads = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    threads = max(1, min(6, threads))
    list_file = Path(sys.argv[2]) if len(sys.argv) > 2 else LIST_FILE
    accounts = load_accounts(list_file)
    if not accounts:
        print(f"Không có acc trong {LIST_FILE}")
        return 2
    base = load_config()
    base["chrome_parallel"] = threads > 1
    log.info("Check login %s acc — %s luồng", len(accounts), threads)

    results: list[tuple[str, str, str, str]] = []
    lock = threading.Lock()
    queue = {"i": 0}

    def worker(wid: int) -> None:
        cfg = dict(base)
        if base.get("chrome_parallel"):
            cfg["chrome_debug_port"] = int(base.get("chrome_debug_port") or 9844) + wid
        while True:
            with lock:
                if queue["i"] >= len(accounts):
                    return
                email, pw = accounts[queue["i"]]
                queue["i"] += 1
            t0 = time.time()
            status, detail = check_one(cfg, email, pw)
            dt = time.time() - t0
            log.info("[%s/%s] %s → %s %s (%.0fs)", queue["i"], len(accounts), email, status, detail[:60], dt)
            with lock:
                results.append((email, pw, status, detail))

    with ThreadPoolExecutor(max_workers=threads) as ex:
        for _ in ex.map(worker, range(threads)):
            pass

    OUT_FILE.write_text(
        "\n".join(f"{e}|{p}|{s}|{d}" for e, p, s, d in results) + "\n",
        encoding="utf-8",
    )
    grp = lambda s: [r for r in results if r[2] == s]  # noqa: E731
    ok_mk, ok_otp = grp("OK_MK"), grp("OK_OTP")
    sai, hong, loi, chan = grp("SAI_MK"), grp("HONG_OTP"), grp("LOI"), grp("BI_CHAN")
    print(
        f"\n=== KẾT QUẢ: {len(ok_mk)} OK mk · {len(ok_otp)} OK otp · "
        f"{len(sai)} sai mk · {len(chan)} bị Canva chặn · "
        f"{len(hong)} OTP hỏng · {len(loi)} lỗi ==="
    )
    for e, _p, s, d in results:
        print(f"  {s:9s} {e}  {d[:70]}")
    print(f"Chi tiết: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
