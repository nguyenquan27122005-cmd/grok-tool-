"""Push Canva success → Google Sheet tab `canva` (cùng webapp Grok)."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_log = logging.getLogger(__name__)

from canreg.paths import GROK_ROOT, ROOT

SHEET_ID = "1SeghtwP7_AgwPyH8fSXiUWsW6zbf8R0_HmkfEHtf_GI"
TAB = "canva"


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
    if p in ("guerrilla", "guerrillamail") or "guerrilla" in domain or domain in (
        "sharklasers.com",
        "grr.la",
        "pokemail.net",
        "spam4.me",
    ):
        return f"Guerrilla · https://www.guerrillamail.com/  (dán {email})"
    if p == "hotmail" or domain in ("outlook.com", "hotmail.com", "live.com", "msn.com"):
        return "Hotmail / Outlook (inbox acc)"
    if "azpop" in p:
        return "Azpop · https://azpopmail.com"
    if "tmail" in p or "wibu" in p or "wibucrypto" in domain:
        return "tmail · https://tmail.wibucrypto.pro"
    return provider or domain or "—"


def _offer_cell(offer: dict[str, Any] | None) -> str:
    offer = offer or {}
    if offer.get("has_offer") or offer.get("is_pro"):
        plan = str(offer.get("plan") or offer.get("summary") or "Pro")
        exp = str(offer.get("expire") or "").strip()
        left = str(offer.get("remaining") or "").strip()
        bits = [plan]
        if left:
            bits.append(f"còn {left}")
        if exp:
            bits.append(f"hết {exp}")
        return " · ".join(bits)
    return "Free · chưa có gói (0 tháng)"


def has_sheet_offer(offer: dict[str, Any] | None) -> bool:
    offer = offer or {}
    if offer.get("has_offer") or offer.get("is_pro"):
        return True
    summary = str(offer.get("summary") or "").strip().lower()
    if summary and summary not in ("no_offer", "none", "free", "—", "-", "error"):
        if not summary.startswith("error"):
            return True
    return False


def append_canva_account(
    email: str,
    password: str,
    status: str,
    ts: str = "",
    *,
    provider: str = "",
    offer: dict[str, Any] | None = None,
) -> str:
    offer = offer or {}
    gs = load_gs_config()
    if gs.get("enabled") is False:
        return "google_sheets disabled"
    url = str(gs.get("webapp_url") or "").strip()
    sid = str(gs.get("spreadsheet_id") or SHEET_ID).strip()
    if not url or not sid:
        return "sheet chưa cấu hình"
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
            "offer": _offer_cell(offer),
        },
    }
    # Apps Script webapp từ chối POST application/json sau redirect (404) —
    # bắt buộc gửi JSON string với Content-Type text/plain. Endpoint /exec
    # thi thoảng vẫn trả 404 HTML lỗi phía Google → thử lại 1 lần.
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "text/plain;charset=utf-8"}
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            r = requests.post(url, data=data, headers=headers, timeout=30, allow_redirects=True)
            if r.status_code < 400:
                break
            last_err = RuntimeError(f"webapp HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            last_err = e
        if attempt == 1:
            time.sleep(2)
    else:
        raise last_err if last_err else RuntimeError("webapp POST failed")
    j = r.json()
    if not isinstance(j, dict) or j.get("ok") is not True:
        raise RuntimeError(j.get("error") if isinstance(j, dict) else str(j))
    return f"append ok: {j.get('result') or j}"
