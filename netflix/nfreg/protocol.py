"""Netflix HTTP probe. Signup is a JS SPA and ends at a paid plan.

This backend:
- GETs public signup/login pages and dumps HTML for later tuning
- never posts payment / card / billing payloads
- returns protocol_need_browser unless a later capture finds a real email API

Chrome (`--backend browser`) is the path that actually fills the form.
"""

from __future__ import annotations

import json
from typing import Any

from nfreg.log import log
from nfreg.paths import DATA

SIGNUP_URL = "https://www.netflix.com/signup"
LOGIN_URL = "https://www.netflix.com/login"

# Public wizard pages only (help.netflix.com/node/112419). Never GET/POST payment.
PROBE_GET = (
    SIGNUP_URL,
    "https://www.netflix.com/signup/planform",
    "https://www.netflix.com/signup/registration",
    "https://www.netflix.com/signup/password",
    LOGIN_URL,
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
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return s


def _dump(name: str, payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2)[:80_000], encoding="utf-8")


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail,
) -> dict[str, Any]:
    del wait_mail, password  # OTP/password belong to the browser path
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
                    "snippet": (r.text or "")[:400],
                }
            )
            log.info("[protocol] GET %s → %s (%s bytes)", url, r.status_code, len(r.text or ""))
        except Exception as e:
            hits.append({"url": url, "error": str(e)[:180]})
            log.warning("[protocol] GET %s fail: %s", url, e)

    _dump(
        "last_protocol.json",
        {
            "step": "probe",
            "email": email,
            "hits": hits,
            "note": "Netflix signup is SPA + paid plan. Use --backend browser. Payment is out of scope.",
        },
    )
    return {
        "ok": False,
        "status": "error:protocol_need_browser",
        "detail": "Netflix không có HTTP signup công khai ổn định — chạy CHAY_REG.bat --backend browser",
        "session": {"email": email, "hits": len(hits)},
    }
