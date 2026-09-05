"""Đọc quota / trial Z.ai sau khi session sống."""

from __future__ import annotations

import json
from typing import Any

from zaireg.log import log
from zaireg.paths import DATA


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _pick_tokens(blob: dict[str, Any]) -> float:
    text_keys = (
        "remaining",
        "remain",
        "balance",
        "quota",
        "tokens",
        "token_balance",
        "left",
        "available",
    )
    data = blob.get("data") if isinstance(blob.get("data"), dict) else blob
    if not isinstance(data, dict):
        return 0.0
    for k in text_keys:
        if k in data:
            n = _num(data.get(k))
            if n > 0:
                return n
    # nested
    for v in data.values():
        if isinstance(v, dict):
            n = _pick_tokens(v)
            if n > 0:
                return n
    return 0.0


def check_zai_quota(client) -> dict[str, Any]:
    usage = {}
    sub = {}
    try:
        usage = client.plan_usage()
    except Exception as e:
        log.debug("plan-usage: %s", e)
    try:
        sub = client.subscription()
    except Exception as e:
        log.debug("subscription: %s", e)

    tokens = max(_pick_tokens(usage), _pick_tokens(sub))
    plan = ""
    for blob in (usage, sub):
        data = blob.get("data") if isinstance(blob.get("data"), dict) else blob
        if isinstance(data, dict):
            plan = str(data.get("plan") or data.get("plan_name") or data.get("tier") or plan)

    summary = "no_offer"
    if tokens >= 50_000_000:
        summary = f"weekend_100m:{int(tokens)}"
    elif tokens >= 1_000_000:
        summary = f"trial:{int(tokens)}"
    elif tokens > 0:
        summary = f"quota:{int(tokens)}"
    elif plan:
        summary = f"plan:{plan}"

    out = {
        "ok": tokens > 0 or bool(plan),
        "summary": summary,
        "tokens": int(tokens) if tokens else 0,
        "plan": plan,
        "has_offer": tokens > 0 or bool(plan and plan.lower() not in ("none", "free", "")),
        "usage": usage,
        "subscription": sub,
    }
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "last_offer.json").write_text(
            json.dumps(out, ensure_ascii=False, default=str)[:8000],
            encoding="utf-8",
        )
    except Exception:
        pass
    return out
