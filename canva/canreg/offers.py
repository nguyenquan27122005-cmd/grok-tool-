"""Đọc plan Canva (Pro / Education / Free) sau khi session sống."""

from __future__ import annotations

import json
from typing import Any

from canreg.log import log
from canreg.paths import DATA


_PRO_OK = (
    "you're a pro",
    "you are a pro",
    "pro member",
    "pro plan",
    "welcome to canva pro",
    "canva pro is active",
    "your pro subscription",
    "pro trial",
    "trial ends",
)
_PRO_CTA = (
    "upgrade to pro",
    "try canva pro",
    "go pro",
    "get pro",
    "try pro",
)


def offer_from_page(url: str, body: str) -> dict[str, Any]:
    low = f"{url} {body}".lower()
    plan = "free"
    path = (url or "").lower()
    billing = any(x in path for x in ("/settings", "/billing", "/subscription"))
    if billing and ("canva education" in low or "education plan" in low):
        plan = "education"
    elif billing and ("canva teams" in low or "canva for teams" in low):
        plan = "teams"
    elif any(x in low for x in _PRO_OK) and not any(x in low for x in _PRO_CTA):
        plan = "pro"
    elif billing and "free plan" in low:
        plan = "free"
    summary = plan if plan != "free" else "no_offer"
    return {
        "ok": plan != "free",
        "summary": summary,
        "plan": plan,
        "has_offer": plan != "free",
        "is_pro": plan in ("pro", "education", "teams"),
    }


def check_canva_offer(session) -> dict[str, Any]:
    """Best-effort: vài endpoint ajax; không có thì no_offer."""
    out: dict[str, Any] = {
        "ok": False,
        "summary": "no_offer",
        "plan": "",
        "has_offer": False,
    }
    urls = (
        "https://www.canva.com/_ajax/csrf3/subscription",
        "https://www.canva.com/_ajax/subscription",
        "https://www.canva.com/settings/",
    )
    for url in urls:
        try:
            r = session.get(url, timeout=20)
        except Exception as e:
            log.debug("offer GET %s: %s", url, e)
            continue
        text = (r.text or "")[:4000]
        parsed = offer_from_page(url, text)
        if parsed.get("has_offer"):
            parsed["http"] = r.status_code
            out = parsed
            break
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "last_offer.json").write_text(
            json.dumps(out, ensure_ascii=False, default=str)[:4000],
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("Check offer Canva lỗi: %s — có thể bỏ sót gói Pro/trial", e)
    return out
