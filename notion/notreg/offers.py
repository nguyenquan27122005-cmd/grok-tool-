"""Read Notion plan / trial after token_v2.

Unofficial www.notion.so/api/v3 (same surface as notion-py / token_v2 tools).
Startup 1/3/6 month Business offers are applied by Notion after
https://www.notion.so/startups-apply — this module only *reads* what's on the workspace.
"""

from __future__ import annotations

import json
import re
from typing import Any

from notreg.log import log
from notreg.paths import DATA

API = "https://www.notion.so/api/v3"


def _session(config: dict[str, Any], token_v2: str = ""):
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
            "notion-client-version": "23.13.0.3272",
        }
    )
    if token_v2:
        try:
            s.cookies.set("token_v2", token_v2, domain=".notion.so")
        except Exception:
            s.cookies.set("token_v2", token_v2)
    return s


def _post(s, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = s.post(f"{API}/{path}", json=payload, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"raw": (r.text or "")[:400]}
    if not isinstance(data, dict):
        data = {"value": data}
    data["_http"] = r.status_code
    return data


def parse_offer(blob: dict[str, Any] | str) -> dict[str, Any]:
    text = blob if isinstance(blob, str) else json.dumps(blob, default=str)
    low = text.lower()
    months = 0
    m = re.search(r"\b([136])\s*[- ]?(?:month|tháng|mo)\b", low)
    if m:
        months = int(m.group(1))
    if "6 month" in low or "6-month" in low or "six month" in low:
        months = 6
    elif "3 month" in low or "3-month" in low or "three month" in low:
        months = 3
    elif re.search(r"\b1 month\b|\bone month\b|1-month", low):
        months = 1

    plan = "free"
    if "business" in low:
        plan = "business"
    elif "education" in low or "student" in low:
        plan = "education"
    elif "plus" in low or "personal_plan" in low:
        plan = "plus"
    trial = bool(re.search(r"trial|complimentary|startup offer|free month", low))
    has = months in (1, 3, 6) or (trial and plan != "free") or plan in ("business", "plus", "education")
    if months:
        summary = f"{plan} · {months} tháng"
    elif trial:
        summary = f"{plan} trial"
    elif plan != "free":
        summary = plan
    else:
        summary = "free"
    return {
        "has_offer": has,
        "months": months,
        "plan": plan,
        "trial": trial,
        "summary": summary,
    }


def check_subscription(config: dict[str, Any], token_v2: str) -> dict[str, Any]:
    if not token_v2:
        return {"ok": False, "has_offer": False, "summary": "no_token"}
    s = _session(config, token_v2)
    spaces = _post(s, "getSpaces", {})
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_spaces.json").write_text(
        json.dumps(spaces, ensure_ascii=False, default=str)[:80_000], encoding="utf-8"
    )
    space_id = ""
    try:
        space_map = (spaces.get("space") or spaces.get("spaces") or {})
        if isinstance(space_map, dict) and space_map:
            space_id = next(iter(space_map.keys()))
        elif isinstance(spaces.get("spaceIds"), list) and spaces["spaceIds"]:
            space_id = str(spaces["spaceIds"][0])
    except Exception:
        space_id = ""
    sub: dict[str, Any] = {}
    if space_id:
        sub = _post(s, "getSubscriptionData", {"spaceId": space_id})
        (DATA / "last_subscription.json").write_text(
            json.dumps(sub, ensure_ascii=False, default=str)[:80_000], encoding="utf-8"
        )
        log.info("[offer] getSubscriptionData HTTP %s space=%s", sub.get("_http"), space_id[:8])
    offer = parse_offer({"spaces": spaces, "sub": sub})
    offer["ok"] = True
    offer["space_id"] = space_id
    log.info("[offer] %s", offer.get("summary"))
    return offer
