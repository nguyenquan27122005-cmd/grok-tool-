"""Push Netflix ledger → Google Sheet tab `netflix` (same webapp as Grok)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_log = logging.getLogger(__name__)

from nfreg.paths import GROK_ROOT, ROOT

SHEET_ID = "1SeghtwP7_AgwPyH8fSXiUWsW6zbf8R0_HmkfEHtf_GI"
TAB = "netflix"


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


def mail_inbox_label(email: str, provider: str = "") -> str:
    p = (provider or "").strip().lower()
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if p in ("guerrilla", "guerrillamail") or "guerrillamail" in domain or domain in ("grr.la", "sharklasers.com"):
        return f"Guerrilla · https://www.guerrillamail.com/  (dán {email})"
    if p == "hotmail" or domain in ("outlook.com", "hotmail.com", "live.com", "msn.com"):
        return "Hotmail / Outlook (inbox acc)"
    if "azpop" in p:
        return "Azpop · https://azpopmail.com"
    if p in ("tmail_wibu", "tmail") or "wibu" in p or "wibucrypto" in domain or domain.endswith(".name.ng"):
        return f"tmail · https://tmail.wibucrypto.pro  (dán {email})"
    return provider or domain or "—"


def append_account(
    email: str,
    password: str,
    status: str,
    ts: str = "",
    *,
    provider: str = "",
    extra: str = "",
) -> str:
    gs = load_gs_config()
    if gs.get("enabled") is False:
        return "google_sheets disabled"
    url = str(gs.get("webapp_url") or "").strip()
    sid = str(gs.get("spreadsheet_id") or SHEET_ID).strip()
    if not url or not sid:
        return "sheet chưa cấu hình"
    try:
        ensure_tab(gs, url, sid)
    except Exception:
        pass
    now = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            "mail_inbox": mail_inbox_label(email, provider),
            "offer": extra or "—",
        },
    }
    r = requests.post(url, json=body, timeout=90, allow_redirects=True)
    if r.status_code >= 400:
        raise RuntimeError(f"webapp HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    if not isinstance(j, dict) or j.get("ok") is not True:
        raise RuntimeError(j.get("error") if isinstance(j, dict) else str(j))
    return f"append ok: {j.get('result') or j}"


def ensure_tab(gs: dict[str, Any] | None = None, url: str = "", sid: str = "") -> str:
    gs = gs or load_gs_config()
    url = url or str(gs.get("webapp_url") or "").strip()
    sid = sid or str(gs.get("spreadsheet_id") or SHEET_ID).strip()
    if not url or not sid:
        return "sheet chưa cấu hình"
    body = {
        "action": "ensure_tab",
        "secret": gs.get("webapp_secret") or "",
        "spreadsheet_id": sid,
        "tab": TAB,
    }
    r = requests.post(url, json=body, timeout=90, allow_redirects=True)
    if r.status_code >= 400:
        raise RuntimeError(f"webapp HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    if not isinstance(j, dict) or j.get("ok") is not True:
        raise RuntimeError(j.get("error") if isinstance(j, dict) else str(j))
    return f"ensure ok: {j.get('result') or j}"
