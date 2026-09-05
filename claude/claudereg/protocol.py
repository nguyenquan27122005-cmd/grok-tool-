"""HTTP probe for Claude.ai signup.

Public references (see SOURCES.md):
- claude.ai/login (email + 6-digit code)
- console.anthropic.com (API console, often phone-gated)

Anthropic does not publish a signup API. This module probes known login
surfaces, records the response in data/last_protocol.json, and yields
to Chrome when captcha / phone / unknown JSON appears.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from curl_cffi import requests  # TLS fingerprint = Chrome thật, không khai "Python"

from claudereg.log import log
from claudereg.paths import DATA

LOGIN = "https://claude.ai/login"
CANDIDATES = (
    ("POST", "https://claude.ai/api/auth/send_magic_link"),
    ("POST", "https://claude.ai/api/auth/email"),
    ("POST", "https://claude.ai/api/email_login"),
    ("POST", "https://claude.ai/login"),
)


def _dump(payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_protocol.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)[:12000],
        encoding="utf-8",
    )


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    s = requests.Session(impersonate="chrome131")
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://claude.ai",
            "Referer": LOGIN,
        }
    )
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}

    try:
        boot = s.get(LOGIN, timeout=25)
    except Exception as e:
        out = {"ok": False, "status": "error:login_get", "detail": str(e)[:200]}
        _dump(out)
        return out

    hits: list[dict[str, Any]] = []
    bodies = (
        {"email": email},
        {"email": email, "password": password},
        {"email_address": email},
    )
    for method, url in CANDIDATES:
        for body in bodies:
            try:
                r = s.request(method, url, json=body, timeout=20)
            except Exception as e:
                hits.append({"url": url, "error": str(e)[:120]})
                continue
            text = (r.text or "")[:400]
            hits.append({"url": url, "status": r.status_code, "body": text})
            low = text.lower()
            if r.status_code in (401, 403) and ("captcha" in low or "turnstile" in low):
                out = {
                    "ok": False,
                    "status": "error:need_captcha",
                    "detail": f"{url} {r.status_code}",
                    "hits": hits,
                    "boot": boot.status_code,
                }
                _dump(out)
                log.warning("protocol captcha: %s", url)
                return out
            if "phone" in low and r.status_code < 500:
                out = {
                    "ok": False,
                    "status": "error:need_phone",
                    "detail": text[:180],
                    "hits": hits,
                }
                _dump(out)
                return out

    out = {
        "ok": False,
        "status": "error:need_browser",
        "detail": "Claude không có signup HTTP công khai — dùng Chrome",
        "hits": hits,
        "boot": boot.status_code,
    }
    _dump(out)
    log.info("protocol: không có endpoint signup công khai → browser")
    return out
