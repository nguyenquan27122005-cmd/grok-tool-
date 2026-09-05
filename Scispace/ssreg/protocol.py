"""SciSpace HTTP — signup thuần KHÔNG OTP, KHÔNG captcha.

POST scispace.com/api/auth/signup
     {"full_name", "email", "password", "invitation_key": null}
→ 201 {"auth_status":"success", ...} — session access_token nằm trong cookies.
AWS WAF challenge chỉ là JS challenge trên trang web; API nhận thẳng
request từ curl_cffi (impersonate chrome) không cần giải gì.
"""

from __future__ import annotations

from typing import Any

from curl_cffi import requests as creq

from ssreg.log import log
from ssreg.paths import DATA

BASE = "https://scispace.com"
SIGNUP_URL = BASE + "/signup"


def _session(config: dict[str, Any]):
    s = creq.Session(impersonate="chrome131")
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update(
        {
            "Origin": BASE,
            "Referer": SIGNUP_URL,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
    )
    return s


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    full_name: str,
) -> dict[str, Any]:
    s = _session(config)
    try:
        s.get(SIGNUP_URL, timeout=25)  # warm-up (cookie WAF nếu có)
    except Exception as e:
        log.debug("signup GET: %s", e)

    log.info("[protocol] POST /api/auth/signup %s", email)
    try:
        r = s.post(
            f"{BASE}/api/auth/signup",
            json={
                "full_name": full_name,
                "email": email,
                "password": password,
                "invitation_key": None,
            },
            timeout=30,
        )
    except Exception as e:
        return {"ok": False, "status": "error:protocol_network", "detail": str(e)[:160]}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_protocol.json").write_text(
        str(r.status_code) + " " + r.text[:2000], encoding="utf-8"
    )
    body = r.text[:300]
    if r.status_code in (200, 201):
        log.info("[protocol] signup OK — %s", body[:120])
        return {"ok": True, "status": "success", "url": "https://scispace.com/"}
    low = body.lower()
    if "already" in low or "exists" in low or "in use" in low:
        return {"ok": False, "status": "error:email_in_use", "detail": body}
    if r.status_code == 429 or "rate" in low or "too many" in low:
        return {"ok": False, "status": "error:rate_limit", "detail": body}
    return {"ok": False, "status": f"error:protocol_{r.status_code}", "detail": body}
