"""Notion HTTP: sendTemporaryPassword → magic link / login code → token_v2.

Public unofficial endpoints used by community tools (notion-py / notion-down):
POST https://www.notion.so/api/v3/sendTemporaryPassword
GET  magic link from mail (sets token_v2)
"""

from __future__ import annotations

import json
from typing import Any

from notreg.log import log
from notreg.offers import check_subscription
from notreg.paths import DATA

API = "https://www.notion.so/api/v3"
SIGNUP_URL = "https://www.notion.so/signup"


def _session(config: dict[str, Any]):
    proxy = str(config.get("proxy") or "").strip()
    try:
        from curl_cffi import requests as creq

        s = creq.Session(impersonate="chrome131")
    except Exception:
        import requests as creq

        s = creq.Session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://www.notion.so",
            "Referer": SIGNUP_URL,
            "notion-client-version": "23.13.0.3272",
        }
    )
    return s


def _token_v2(s) -> str:
    try:
        jar = getattr(s, "cookies", None)
        if jar is None:
            return ""
        if hasattr(jar, "get"):
            return str(jar.get("token_v2") or "")
        for c in jar:
            if getattr(c, "name", "") == "token_v2":
                return str(c.value or "")
    except Exception:
        return ""
    return ""


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail,
) -> dict[str, Any]:
    del password
    DATA.mkdir(parents=True, exist_ok=True)
    s = _session(config)
    try:
        s.get(SIGNUP_URL, timeout=25)
    except Exception as e:
        log.debug("signup GET: %s", e)

    body = {"email": email, "disableLoginLink": False}
    log.info("[protocol] POST sendTemporaryPassword %s", email)
    r = s.post(f"{API}/sendTemporaryPassword", json=body, timeout=30)
    snippet = (r.text or "")[:300]
    log.info("[protocol] sendTemporaryPassword HTTP %s %s", r.status_code, snippet[:180])
    (DATA / "last_protocol.json").write_text(
        json.dumps({"step": "sendTemporaryPassword", "status": r.status_code, "body": r.text[:2000]}, ensure_ascii=False),
        encoding="utf-8",
    )
    if r.status_code >= 400:
        low = (r.text or "").lower()
        if "captcha" in low:
            return {"ok": False, "status": "error:need_captcha", "detail": snippet}
        return {"ok": False, "status": f"error:protocol_send_{r.status_code}", "detail": snippet}

    log.info("[protocol] chờ mail Notion…")
    proof = wait_mail() or {}
    link = (proof.get("link") or "").strip()
    code = (proof.get("code") or "").strip()
    if link:
        log.info("[protocol] GET magic %s", link[:90])
        try:
            r2 = s.get(link, timeout=30, allow_redirects=True)
            log.info("[protocol] magic HTTP %s final=%s", r2.status_code, str(getattr(r2, "url", ""))[:80])
        except Exception as e:
            return {"ok": False, "status": "error:protocol_magic_get", "detail": str(e)[:160]}
    elif code:
        log.info("[protocol] loginWithEmail code")
        r3 = s.post(
            f"{API}/loginWithEmail",
            json={"email": email, "password": code},
            timeout=30,
        )
        log.info("[protocol] loginWithEmail HTTP %s %s", r3.status_code, (r3.text or "")[:160])
        if r3.status_code >= 400:
            return {
                "ok": False,
                "status": "error:protocol_need_browser_verify",
                "detail": (r3.text or "")[:180],
            }
    else:
        return {"ok": False, "status": "error:protocol_otp_timeout", "detail": "không thấy magic link/code"}

    token = _token_v2(s)
    if not token:
        return {
            "ok": False,
            "status": "error:protocol_need_browser",
            "detail": "Không bắt được token_v2 — chạy --backend browser",
        }
    offer = check_subscription(config, token)
    return {
        "ok": True,
        "status": "success",
        "session": {"email": email, "token_v2": token[:12] + "…", "token": token},
        "offer": offer,
    }
