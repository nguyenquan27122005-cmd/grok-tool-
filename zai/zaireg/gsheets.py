"""Push Z.ai success → Google Sheet tab `zai` (chỉ khi có quota/offer)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_log = logging.getLogger(__name__)

from zaireg.paths import GROK_ROOT, ROOT

SHEET_ID = "1SeghtwP7_AgwPyH8fSXiUWsW6zbf8R0_HmkfEHtf_GI"
TAB = "zai"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def load_gs_config() -> dict[str, Any]:
    local = _load_json(ROOT / "config.json").get("google_sheets") or {}
    grok = _load_json(GROK_ROOT / "config.json").get("google_sheets") or {}
    gs = dict(grok)
    gs.update({k: v for k, v in local.items() if v not in ("", None)})
    gs["tab"] = str(local.get("tab") or TAB)
    gs.setdefault("spreadsheet_id", SHEET_ID)
    gs.pop("gid", None)
    secret = str(gs.get("webapp_secret") or "").strip()
    if not secret or secret.upper() in ("CHANGE_ME", "CHANGEME"):
        env_sec = os.environ.get("GSHEETS_WEBAPP_SECRET", "").strip()
        if env_sec:
            gs["webapp_secret"] = env_sec
        else:
            gs["webapp_secret"] = "grok-overnight-export"
            _log.warning(
                "gsheets: webapp_secret chua cau hinh — dung mac dinh yeu. "
                "Set gsheets.webapp_secret trong config.json (dong bo Apps Script) "
                "hoac env GSHEETS_WEBAPP_SECRET."
            )
    return gs


def has_sheet_offer(offer: dict[str, Any] | None) -> bool:
    offer = offer or {}
    if offer.get("has_offer"):
        return True
    if int(offer.get("tokens") or 0) > 0:
        return True
    summary = str(offer.get("summary") or "").strip().lower()
    if summary.startswith(("weekend", "trial", "quota", "plan:")):
        return True
    return False


def append_zai_account(
    email: str,
    password: str,
    status: str,
    ts: str = "",
    *,
    provider: str = "",
    offer: dict[str, Any] | None = None,
) -> str:
    offer = offer or {}
    if not has_sheet_offer(offer):
        return "skip: không có quota/offer — không ghi sheet"
    gs = load_gs_config()
    if gs.get("enabled") is False:
        return "google_sheets disabled"
    url = str(gs.get("webapp_url") or "").strip()
    sid = str(gs.get("spreadsheet_id") or SHEET_ID).strip()
    if not url or not sid:
        return "sheet chưa cấu hình"
    now = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inbox = "Hotmail / Outlook"
    body = {
        "action": "append",
        "secret": gs.get("webapp_secret") or "",
        "spreadsheet_id": sid,
        "tab": TAB,
        "account": {
            "email": email,
            "password": password,
            "name": status or "success",
            "status": status,
            "time": now,
            "reg_date": now.split(" ")[0],
            "mail_inbox": inbox,
            "offer": offer.get("summary") or "—",
        },
    }
    r = requests.post(url, json=body, timeout=90, allow_redirects=True)
    if r.status_code >= 400:
        raise RuntimeError(f"webapp HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    if not isinstance(j, dict) or j.get("ok") is not True:
        raise RuntimeError(j.get("error") if isinstance(j, dict) else str(j))
    return f"append ok: {j.get('result') or j}"
