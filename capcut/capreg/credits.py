"""Đọc số credit của account Dreamina qua commerce benefits API.

Endpoint rút ra từ JS bundle của dreamina.capcut.com:
POST https://commerce-api-sg.capcut.com/commerce/v3/benefits/batch_get_user_benefit
body {"queryList":[{resourceType:"aigc",resourceId:"get_all",benefitTypeList:[]},…]}
→ {"ret":"0","data":{"total_credits":N,"credits_detail":{...},"asset_list":…}}

Chỉ cần cookie passport (sessionid) trong client.session — không cần sign header.
"""

from __future__ import annotations

from typing import Any

import requests

from capreg.log import log

CREDIT_URL = (
    "https://commerce-api-sg.capcut.com/commerce/v3/benefits/batch_get_user_benefit"
)

_QUERY = {
    "queryList": [
        {"resourceType": "aigc", "resourceId": "get_all", "benefitTypeList": []},
        {"resourceType": "normal_func", "resourceId": "get_all", "benefitTypeList": []},
    ]
}


def fetch_total_credits(client) -> dict[str, Any]:
    """Trả về {"ok","total","detail","summary"} — không bao giờ raise."""
    try:
        r = client.session.post(
            CREDIT_URL,
            json=_QUERY,
            params={"aid": getattr(client, "app_id", ""), "device_platform": "web"},
            headers={
                "Content-Type": "application/json",
                "Origin": "https://dreamina.capcut.com",
                "Referer": "https://dreamina.capcut.com/",
                **client.headers(),
            },
            timeout=20,
        )
    except requests.RequestException as e:
        return {"ok": False, "total": -1, "summary": f"http_err:{str(e)[:60]}"}
    if r.status_code >= 400:
        return {"ok": False, "total": -1, "summary": f"http_{r.status_code}"}
    try:
        j = r.json()
    except ValueError:
        return {"ok": False, "total": -1, "summary": "not_json"}
    data = j.get("data") if isinstance(j.get("data"), dict) else {}
    ret = str(j.get("ret") or "")
    if ret not in ("0", "") or "total_credits" not in data:
        msg = str(j.get("errmsg") or j.get("message") or ret)[:80]
        return {"ok": False, "total": -1, "summary": f"ret:{ret or '?'} {msg}".strip()}
    try:
        total = int(data.get("total_credits") or 0)
    except (TypeError, ValueError):
        total = 0
    detail = data.get("credits_detail")
    log.info("[credit] Dreamina total=%s detail=%s", total, detail if detail else "{}")
    return {
        "ok": True,
        "total": total,
        "detail": detail if isinstance(detail, dict) else {},
        "summary": f"{total} credits",
    }
