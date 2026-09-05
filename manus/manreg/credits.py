"""Manus credits after login.

Public API used by CodexBar (steipete/CodexBar ManusUsageFetcher.swift):

POST https://api.manus.im/user.v1.UserService/GetAvailableCredits
Authorization: Bearer <session_id cookie>
Connect-Protocol-Version: 1
body: {}

This is a *session check*, not a signup endpoint.
"""

from __future__ import annotations

from typing import Any

from manreg.log import log

CREDITS_URL = "https://api.manus.im/user.v1.UserService/GetAvailableCredits"


def session_token_from_cookie(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if "=" not in text and ";" not in text:
        return text
    for part in text.split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        if name.strip().lower() == "session_id":
            return value.strip()
    return ""


def fetch_credits(config: dict[str, Any], session_token: str) -> dict[str, Any]:
    token = session_token_from_cookie(session_token) or (session_token or "").strip()
    if not token:
        return {"ok": False, "status": "error:no_session_id"}
    proxy = str(config.get("proxy") or "").strip()
    try:
        from curl_cffi import requests as creq

        s = creq.Session(impersonate="chrome131")
    except Exception:
        import requests as creq

        s = creq.Session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Origin": "https://manus.im",
        "Referer": "https://manus.im/",
        "Connect-Protocol-Version": "1",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    try:
        r = s.post(CREDITS_URL, json={}, headers=headers, timeout=20)
    except Exception as e:
        return {"ok": False, "status": "error:credits_net", "detail": str(e)[:160]}
    body = (r.text or "")[:2000]
    log.info("[credits] HTTP %s %s", r.status_code, body[:180])
    if r.status_code in (401, 403):
        return {"ok": False, "status": "error:invalid_session", "http": r.status_code}
    if r.status_code >= 400:
        return {"ok": False, "status": f"error:credits_{r.status_code}", "detail": body[:200]}
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "status": "error:credits_parse", "detail": body[:200]}
    if not isinstance(data, dict):
        return {"ok": False, "status": "error:credits_shape"}
    inner = data.get("data") or data.get("result") or data.get("response") or data.get("availableCredits") or data
    if not isinstance(inner, dict):
        inner = data
    keys = (
        "totalCredits",
        "freeCredits",
        "periodicCredits",
        "proMonthlyCredits",
        "refreshCredits",
        "maxRefreshCredits",
        "eventCredits",
    )
    if not any(k in inner for k in keys):
        return {"ok": False, "status": "error:credits_empty", "raw": inner}
    summary = (
        f"total={inner.get('totalCredits')} free={inner.get('freeCredits')} "
        f"pro={inner.get('proMonthlyCredits')} refresh={inner.get('refreshCredits')}"
    )
    return {"ok": True, "status": "ok", "summary": summary.strip(), "credits": inner}
