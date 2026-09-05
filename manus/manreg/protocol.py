"""Manus HTTP probe. Login/signup is the SPA at https://manus.im/login.

Tries a few public auth URLs. If they 404 / change, fall back to Chrome.
Does not implement OAuth-token theft or invite-code farming.
"""

from __future__ import annotations

import json
from typing import Any

from manreg.log import log
from manreg.paths import DATA

LOGIN_URL = "https://manus.im/login"
APP_URL = "https://manus.im/"

PROBE_GET = (
    LOGIN_URL,
    APP_URL,
    "https://manus.im/app",
    "https://manus.im/signup",
)

# Candidate send-code endpoints — recorded when browser capture finds a real one.
# Auth send-code is not public (OpenCLI: /api/* needs session). Credits IS public-with-session
# (CodexBar). Do not treat GetAvailableCredits as a signup API.
CANDIDATE_POST = (
    "https://api.manus.im/v1/auth/email/send",
    "https://manus.im/api/auth/email/send",
    "https://manus.im/api/v1/auth/send-code",
    "https://api.manus.im/auth/send-code",
)


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
            "Origin": "https://manus.im",
            "Referer": LOGIN_URL,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return s


def _dump(payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_protocol.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)[:80_000],
        encoding="utf-8",
    )


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail,
) -> dict[str, Any]:
    s = _session(config)
    hits: list[dict[str, Any]] = []

    for url in PROBE_GET:
        try:
            r = s.get(url, timeout=25, allow_redirects=True)
            hits.append(
                {
                    "url": url,
                    "final": str(getattr(r, "url", "") or url),
                    "status": r.status_code,
                    "len": len(r.text or ""),
                    "snippet": (r.text or "")[:300],
                }
            )
            log.info("[protocol] GET %s → %s", url, r.status_code)
        except Exception as e:
            hits.append({"url": url, "error": str(e)[:180]})
            log.warning("[protocol] GET %s fail: %s", url, e)

    send_url = str(config.get("send_code_url") or "").strip()
    posts = [send_url] if send_url else list(CANDIDATE_POST)
    payload_keys = (
        {"email": email},
        {"email": email, "locale": "en"},
        {"email": email, "type": "signup"},
    )

    for url in posts:
        if not url:
            continue
        for body in payload_keys:
            try:
                r = s.post(url, json=body, timeout=20)
            except Exception as e:
                hits.append({"post": url, "error": str(e)[:160]})
                continue
            snippet = (r.text or "")[:240]
            hits.append({"post": url, "status": r.status_code, "body": snippet})
            log.info("[protocol] POST %s → %s %s", url, r.status_code, snippet[:120])
            if r.status_code in (200, 201, 202) and "html" not in (r.headers.get("content-type") or "").lower():
                low = (r.text or "").lower()
                if any(x in low for x in ("error", "not found", "404", "invalid")):
                    continue
                log.info("[protocol] send-code có vẻ OK — chờ mail")
                proof = wait_mail() or {}
                _dump({"step": "send_ok", "url": url, "email": email, "proof": proof, "hits": hits})
                if proof.get("link") or proof.get("code"):
                    return {
                        "ok": False,
                        "status": "error:protocol_need_browser_verify",
                        "detail": "Đã gửi mail nhưng verify vẫn cần Chrome (SPA)",
                        "session": {"email": email, "proof": proof, "send_url": url},
                    }
                return {
                    "ok": False,
                    "status": "error:protocol_otp_timeout",
                    "detail": "send-code OK nhưng không thấy mail",
                    "session": {"email": email, "send_url": url},
                }
            if r.status_code not in (404, 405, 501):
                break

    _dump(
        {
            "step": "probe",
            "email": email,
            "hits": hits,
            "note": "Điền send_code_url trong config.json khi capture được endpoint thật. Path chính: --backend browser.",
        }
    )
    del password
    return {
        "ok": False,
        "status": "error:protocol_need_browser",
        "detail": "Manus login là SPA — chạy CHAY_REG.bat --backend browser",
        "session": {"email": email, "hits": len(hits)},
    }
