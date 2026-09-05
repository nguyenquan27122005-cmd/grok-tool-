"""OpenArt HTTP — Clerk email_code flow (không Chrome).

GET  clerk.openart.ai/v1/client                     → cookies client
POST clerk.openart.ai/v1/client/sign_ups            → tạo sign_up (email+password+captcha)
POST .../sign_ups/{id}/prepare_verification         → gửi OTP email (email_code)
POST .../sign_ups/{id}/attempt_verification         → verify OTP → status=complete
"""

from __future__ import annotations

import time
from typing import Any, Callable

from curl_cffi import requests  # TLS fingerprint = Chrome thật, không khai "Python"

from oareg.log import log
from oareg.paths import DATA
from oareg.turnstile import kick_solver, solve_token

CLERK = "https://clerk.openart.ai"
ORIGIN = "https://openart.ai"
SIGNUP_URL = "https://openart.ai/signin"


def _session(config: dict[str, Any]) -> requests.Session:
    s = requests.Session(impersonate="chrome131")
    s.trust_env = False  # không ride system proxy cho Clerk (CF chặn IP lạ)
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update(
        {
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }
    )
    return s


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail: Callable[..., str],
) -> dict[str, Any]:
    """Email đã lấy ở worker; `wait_mail(since_iso=...)` → 6-digit code."""
    kick_solver(config)
    s = _session(config)

    try:
        s.get(f"{CLERK}/v1/client", timeout=20)
    except Exception as e:
        return {"ok": False, "status": "error:protocol_clerk_unreachable", "detail": str(e)[:160]}

    # ---- create sign_up (cần captcha token) ----
    try:
        tok = solve_token(config)
    except Exception as e:
        return {"ok": False, "status": "error:protocol_need_turnstile", "detail": str(e)[:180]}

    log.info("[protocol] POST sign_ups %s", email)
    r = s.post(
        f"{CLERK}/v1/client/sign_ups",
        data={"email_address": email, "password": password, "captcha_token": tok, "captcha_error": ""},
        timeout=30,
    )
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_protocol.json").write_text(
        str(r.status_code) + " " + r.text[:2000], encoding="utf-8"
    )
    errs = (j or {}).get("errors") or []
    if errs:
        code = str(errs[0].get("code") or "")
        msg = str(errs[0].get("long_message") or errs[0].get("message") or "")[:180]
        log.warning("[protocol] create fail: %s — %s", code, msg)
        if "blocked" in code or "temporary" in msg.lower():
            return {"ok": False, "status": "error:email_flagged", "detail": msg}
        return {"ok": False, "status": f"error:protocol_create:{code}", "detail": msg}
    sup = (j or {}).get("response") or {}
    sid = str(sup.get("id") or "")
    if not sid:
        return {"ok": False, "status": "error:protocol_create:no_id", "detail": r.text[:160]}
    log.info("[protocol] sign_up %s status=%s", sid, sup.get("status"))

    # ---- prepare email_code (không cần captcha) ----
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
    r = s.post(
        f"{CLERK}/v1/client/sign_ups/{sid}/prepare_verification",
        data={"strategy": "email_code"},
        timeout=30,
    )
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    errs = (j or {}).get("errors") or []
    if errs:
        code = str(errs[0].get("code") or "")
        return {"ok": False, "status": f"error:protocol_prepare:{code}", "detail": r.text[:180]}
    # Token cho account kế tiếp: giải TRONG lúc acc này đợi OTP (overlap)
    from oareg.turnstile import prefetch_token

    prefetch_token(config)
    log.info("[protocol] OTP đã gửi — chờ mail… (prefetch token acc kế)")

    # ---- wait OTP (mail có thể trễ ~1 phút) ----
    code = ""
    for rnd in range(2):
        code = (wait_mail(since_iso=since) or "").strip()
        if code:
            break
        if rnd == 0:
            # prepare không cần captcha — chỉ gửi lại email_code
            log.warning("[protocol] chưa thấy mail — resend email_code")
            try:
                s.post(
                    f"{CLERK}/v1/client/sign_ups/{sid}/prepare_verification",
                    data={"strategy": "email_code"},
                    timeout=30,
                )
            except Exception as e:
                log.debug("resend prepare: %s", e)
    if not code:
        return {"ok": False, "status": "error:protocol_otp_timeout", "detail": "khong nhan duoc OTP OpenArt"}

    # ---- attempt verification ----
    r = s.post(
        f"{CLERK}/v1/client/sign_ups/{sid}/attempt_verification",
        data={"strategy": "email_code", "code": code},
        timeout=30,
    )
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    errs = (j or {}).get("errors") or []
    if errs:
        code_err = str(errs[0].get("code") or "")
        msg = str(errs[0].get("long_message") or "")[:120]
        return {"ok": False, "status": f"error:protocol_attempt:{code_err}", "detail": msg}
    resp = (j or {}).get("response") or {}
    status = str(resp.get("status") or "")
    session_id = str(resp.get("created_session_id") or "")
    log.info("[protocol] attempt status=%s session=%s", status, session_id or "—")
    if status != "complete":
        return {"ok": False, "status": f"error:protocol_incomplete:{status}", "detail": r.text[:180]}

    return {
        "ok": True,
        "status": "success",
        "url": "https://openart.ai/create",
        "session": {"clerk_session_id": session_id, "sign_up_id": sid, "email": email},
    }
