"""Đọc plan / credit HeyGen ngay sau khi reg xong (session hoặc Bearer token)."""

from __future__ import annotations

import json
import re
from typing import Any

from heyreg.log import log
from heyreg.paths import DATA

# Endpoint web của app.heygen.com (cookie session) — api.heygen.com v2 chỉ
# nhận X-Api-Key nên luôn 401 với token đăng ký mới.
PROBES = (
    "https://app.heygen.com/api/v1/user/info",
    "https://app.heygen.com/api/v1/user/plan",
)

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_OFFER_WORD_RE = re.compile(
    r"\b(pro|max|team|enterprise|unlimited|trial)\b", re.I
)
_FREE_PLAN_RE = re.compile(r"\b(free|starter)\b", re.I)


def _unwrap(blob: Any) -> dict[str, Any]:
    if isinstance(blob, dict) and isinstance(blob.get("data"), dict):
        return blob["data"]
    return blob if isinstance(blob, dict) else {}


def _find_number(data: dict[str, Any], *keys: str) -> float:
    for k in keys:
        for src, v in (
            (k, data.get(k)),
            *(("", sv) for sk, sv in data.items() if k in str(sk).lower()),
        ):
            n = _NUM_RE.search(str(v or "")) if not isinstance(v, (int, float)) else None
            try:
                val = float(v) if isinstance(v, (int, float)) else float(n.group(0))
                if val > 0:
                    return val
            except (AttributeError, ValueError, TypeError):
                continue
    return 0.0


def check_heygen_offer(session: Any, token: str = "") -> dict[str, Any]:
    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    tok = (token or "").strip()
    blobs: list[Any] = []
    for url in PROBES:
        got = False
        for method, extra in (
            ("GET", {}),
            ("POST", {"Content-Type": "application/json"}),
        ):
            if got:
                break
            for auth in (({"Authorization": f"Bearer {tok}"} if tok else {}), ({},)):
                if got:
                    break
                try:
                    h = {**headers, **extra, **auth}
                    r = (
                        session.get(url, headers=h, timeout=20)
                        if method == "GET"
                        else session.post(url, headers=h, json={}, timeout=20)
                    )
                    ct = str(r.headers.get("content-type") or "")
                    body: Any = r.json() if "json" in ct.lower() else {}
                    log.info(
                        "[offer] %s %s HTTP %s body=%s",
                        method,
                        url,
                        r.status_code,
                        str(body)[:150],
                    )
                    if r.status_code < 400 and isinstance(body, dict) and body:
                        blobs.append(body)
                        got = True
                        break
                except Exception as e:
                    log.debug("[offer] %s %s fail: %s", method, url, str(e)[:80])

    data: dict[str, Any] = {}
    for b in blobs:
        u = _unwrap(b)
        if u.get("email") or u.get("plan") or u.get("remaining_quota") is not None or u.get("credit"):
            data = u
            break
        data = data or u

    plan = ""
    for key in ("plan", "plan_name", "tier", "subscription_plan"):
        if data.get(key):
            plan = str(data[key])
            break
    tokens_or_credit = max(
        _find_number(data, "remaining_quota", "credits", "credit_left", "quota"),
        0.0,
    )

    blob_text = json.dumps(data, ensure_ascii=False, default=str)[:2000].lower()
    summary = "no_offer"
    has_offer = False
    m = _OFFER_WORD_RE.search(plan or "")
    if m:
        summary = f"{m.group(1).lower()}:{plan}"
        has_offer = True
    elif tokens_or_credit > 0:
        summary = f"quota:{int(tokens_or_credit)}"
    elif _FREE_PLAN_RE.search(plan or ""):
        summary = f"free:{plan}"
    elif data:
        summary = "unknown"

    out = {
        "ok": bool(data),
        "summary": summary,
        "plan": plan,
        "credits": int(tokens_or_credit) if tokens_or_credit else 0,
        "has_offer": has_offer or _OFFER_WORD_RE.search(blob_text) is not None,
        "raw_keys": sorted(list(_unwrap(blobs[0]).keys()))[:12] if blobs else [],
    }
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "last_offer.json").write_text(
            json.dumps({**out, "blobs": blobs[:3]}, ensure_ascii=False, default=str)[:8000],
            encoding="utf-8",
        )
    except Exception:
        pass
    return out
