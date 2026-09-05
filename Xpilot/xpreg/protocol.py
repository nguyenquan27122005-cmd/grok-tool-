"""X-Pilot HTTP protocol — signup bắt OTP qua email, thuần requests.

POST https://server.x-pilot.ai/auth/sendVerifyEmail {email}
     → {"code":0,"message":"验证码发送成功","data":null}
POST /auth/sign_up {email, password, code}          (code = OTP 6 số từ mail)
     → 201 {"code":201,"message":"register success","data":{"user":...}}
POST /auth/sign_in {login, password}
     → {"code":0,"message":"登录成功","data":{"token":"JWT...","access..."}}
GET  /users/me (Bearer token) → user info (accountType, points, tokens...)

Không captcha, không Cloudflare challenge trên API server.x-pilot.ai;
temp mail không bị chặn. Token JWT sống 7 ngày — checkout chỉ cần
email + password (sign_in lại) nên không cần lưu token.
"""

from __future__ import annotations

from typing import Any, Optional

from curl_cffi import requests  # TLS fingerprint = Chrome thật, không khai "Python"

from xpreg.log import log
from xpreg.paths import DATA

BASE = "https://server.x-pilot.ai"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _headers(token: str = "") -> dict[str, str]:
    h = {
        "User-Agent": UA,
        "Origin": "https://app.x-pilot.ai",
        "Referer": "https://app.x-pilot.ai/",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _session(config: dict[str, Any]) -> requests.Session:
    s = requests.Session(impersonate="chrome131")
    s.trust_env = False
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update(_headers())
    return s


def _post(s: requests.Session, path: str, body: dict, timeout: int = 30):
    return s.post(f"{BASE}{path}", json=body, timeout=timeout)


def send_code(s: requests.Session, email: str) -> dict[str, Any]:
    r = _post(s, "/auth/sendVerifyEmail", {"email": email})
    log.info("[protocol] sendVerifyEmail %s → %s", email, r.text[:120])
    return {"ok": r.status_code == 200, "status_code": r.status_code, "body": r.text[:300]}


def sign_up(s: requests.Session, *, email: str, password: str, code: str) -> dict[str, Any]:
    r = _post(s, "/auth/sign_up", {"email": email, "password": password, "code": code})
    body = r.text[:300]
    try:
        j = r.json()
    except Exception:
        j = {}
    code_j = int(j.get("code") or 0)
    if r.status_code in (200, 201) and code_j in (0, 201):
        log.info("[protocol] sign_up OK — %s", body[:100])
        return {"ok": True, "status": "success", "detail": body}
    low = body.lower()
    if "exist" in low or "already" in low or "in use" in low or code_j in (1002, 1005):
        return {"ok": False, "status": "error:email_in_use", "detail": body}
    if "code" in low and ("invalid" in low or "error" in low or "expire" in low):
        return {"ok": False, "status": "error:otp_invalid", "detail": body}
    if r.status_code == 429 or "rate" in low or "too many" in low:
        return {"ok": False, "status": "error:rate_limit", "detail": body}
    return {"ok": False, "status": f"error:signup_{r.status_code}", "detail": body}


def sign_in(s: requests.Session, *, email: str, password: str) -> dict[str, Any]:
    r = _post(s, "/auth/sign_in", {"login": email, "password": password})
    try:
        j = r.json()
    except Exception:
        j = {}
    token = ((j.get("data") or {}).get("token")) or ""
    if r.status_code == 200 and token:
        return {"ok": True, "status": "success", "token": token}
    return {"ok": False, "status": "error:login_failed", "detail": r.text[:300]}


def me(s: requests.Session, token: str) -> Optional[dict[str, Any]]:
    try:
        r = s.get(f"{BASE}/users/me", headers=_headers(token), timeout=20)
        if r.status_code == 200:
            return ((r.json() or {}).get("data") or {}).get("user") or {}
    except Exception as e:
        log.debug("users/me: %s", e)
    return None
