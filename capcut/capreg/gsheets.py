"""Push CapCut success → Google Sheet tab `capcut` (same webapp as Grok)."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_log = logging.getLogger(__name__)

from capreg.paths import GROK_ROOT, ROOT

SHEET_ID = "1SeghtwP7_AgwPyH8fSXiUWsW6zbf8R0_HmkfEHtf_GI"
TAB = "capcut"


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
    guerrilla_doms = (
        "guerrillamailblock.com",
        "guerrillamail.com",
        "guerrillamail.info",
        "guerrillamail.net",
        "guerrillamail.org",
        "guerrillamail.biz",
        "guerrillamail.de",
        "sharklasers.com",
        "grr.la",
        "pokemail.net",
        "spam4.me",
    )
    if p in ("guerrilla", "guerrillamail") or domain in guerrilla_doms:
        return f"Guerrilla · https://www.guerrillamail.com/  (dán {email})"
    if p == "hotmail" or domain in ("outlook.com", "hotmail.com", "live.com", "msn.com"):
        return "Hotmail / Outlook (inbox acc)"
    if "azpop" in p:
        return "Azpop · https://azpopmail.com"
    if "mail.tm" in p or p == "mailtm":
        return "Mail.tm"
    if p in ("tmail_wibu", "tmail") or "wibu" in p or "wibucrypto" in domain or domain.endswith(".name.ng"):
        return f"tmail · https://tmail.wibucrypto.pro  (dán {email})"
    return provider or domain or "—"


def has_sheet_offer(offer: dict[str, Any] | None, offer_check: dict[str, Any] | None) -> bool:
    """Chỉ coi là có offer khi Pro/trial đã kích hoặc API liệt kê gói — không tính hint trang."""
    offer = offer or {}
    offer_check = offer_check or {}
    if offer_check.get("is_pro") or offer_check.get("is_trial"):
        return True
    avail = offer_check.get("offers_available") or []
    if isinstance(avail, list) and any(str(x).strip() for x in avail):
        return True
    summary = str(offer_check.get("summary") or "").strip().lower()
    if summary and summary not in ("no_offer", "none", "—", "-", "error"):
        if not summary.startswith("error"):
            return True
    label = str(offer.get("label") or "").lower()
    # web_login / trial_7d_page / desktop_e30 chỉ là hint landing, chưa phải offer
    hint_only = {"", "none", "off", "error", "web_login"}
    bits = [b for b in label.replace("+", " ").split() if b]
    real = [
        b
        for b in bits
        if b not in hint_only
        and "web_login" not in b
        and "trial_7d_page" not in b
        and "desktop_e30" not in b
        and "desktop30" not in b
    ]
    return bool(real)


def _parse_expire(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.isdigit():
        n = int(text)
        if n > 10_000_000_000:
            n = n / 1000.0
        try:
            return datetime.fromtimestamp(n)
        except (OverflowError, OSError, ValueError):
            return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            return None
    return None


def remaining_months(offer_check: dict[str, Any] | None) -> tuple[str, str]:
    """Return (months_label, expire_iso). months_label e.g. '3.0 tháng (91 ngày)'."""
    offer_check = offer_check or {}
    days = offer_check.get("trial_days_left")
    if days is None:
        days = offer_check.get("remaining_days")
    try:
        days_n = float(days) if days is not None and str(days).strip() != "" else None
    except (TypeError, ValueError):
        days_n = None
    exp_dt = _parse_expire(str(offer_check.get("expire") or ""))
    if days_n is None and exp_dt is not None:
        days_n = max(0.0, (exp_dt - datetime.now()).total_seconds() / 86400.0)
    exp_txt = exp_dt.strftime("%Y-%m-%d") if exp_dt else str(offer_check.get("expire") or "")
    if days_n is None:
        return ("chưa rõ hạn", exp_txt)
    months = days_n / 30.4375
    if days_n < 1:
        return (f"0 tháng (còn {int(round(days_n * 24))} giờ)", exp_txt)
    if months < 1:
        return (f"{months:.1f} tháng ({int(round(days_n))} ngày)", exp_txt)
    return (f"{months:.1f} tháng ({int(round(days_n))} ngày)", exp_txt)


def offer_label(
    offer: dict[str, Any] | None,
    offer_check: dict[str, Any] | None,
    credits: dict[str, Any] | None = None,
) -> str:
    """Một ô: gói + số tháng còn lại (để cột Sheet hiện tại đọc được).

    Với acc Dreamina (check_credits=true): hiện số credit thay vì nhãn CapCut.
    """
    offer = offer or {}
    offer_check = offer_check or {}
    plan = str(offer_check.get("plan") or "").strip()
    left, exp = remaining_months(offer_check)
    if offer_check.get("is_trial"):
        name = " ".join(x for x in ("Pro trial", plan) if x)
        tail = f" · hết {exp}" if exp else ""
        return f"{name} · còn {left}{tail}"
    if offer_check.get("is_pro"):
        name = " ".join(x for x in ("Pro", plan) if x)
        tail = f" · hết {exp}" if exp else ""
        return f"{name} · còn {left}{tail}"
    if isinstance(credits, dict) and credits.get("ok"):
        return f"Free · {credits.get('total')} credits"
    raw = str(offer.get("label") or offer_check.get("summary") or "")
    hints: list[str] = []
    if "trial_7d" in raw:
        hints.append("trial 7 ngày nếu bấm Join Pro")
    if "desktop_e30" in raw or "e30" in raw:
        hints.append("e30: Pro 1 tháng nếu cài CapCut PC")
    hint = f" · hint: {' / '.join(hints)}" if hints else ""
    return f"Free · chưa có gói (0 tháng){hint}"


def append_capcut_account(
    email: str,
    password: str,
    status: str,
    ts: str = "",
    *,
    provider: str = "",
    offer: dict[str, Any] | None = None,
    offer_check: dict[str, Any] | None = None,
    credits: dict[str, Any] | None = None,
) -> str:
    gs = load_gs_config()
    if gs.get("enabled") is False:
        return "google_sheets disabled"
    url = str(gs.get("webapp_url") or "").strip()
    sid = str(gs.get("spreadsheet_id") or SHEET_ID).strip()
    if not url or not sid:
        return "sheet chưa cấu hình"
    now = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reg_date = now.split(" ")[0]
    body = {
        "action": "append",
        "secret": gs.get("webapp_secret") or "",
        "spreadsheet_id": sid,
        "tab": str(gs.get("tab") or TAB),
        "account": {
            "email": email,
            "password": password,
            "name": status or "success",
            "status": status,
            "time": now,
            "reg_date": reg_date,
            "mail_inbox": mail_inbox_label(email, provider),
            "offer": offer_label(offer, offer_check, credits),
        },
    }
    r = requests.post(url, json=body, timeout=90, allow_redirects=True)
    if r.status_code >= 400:
        raise RuntimeError(f"webapp HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    if not isinstance(j, dict) or j.get("ok") is not True:
        raise RuntimeError(j.get("error") if isinstance(j, dict) else str(j))
    return f"append ok: {j.get('result') or j}"


def ensure_capcut_tab() -> str:
    gs = load_gs_config()
    url = str(gs.get("webapp_url") or "").strip()
    sid = str(gs.get("spreadsheet_id") or SHEET_ID).strip()
    if not url or not sid:
        return "sheet chưa cấu hình"
    body = {
        "action": "ensure_tab",
        "secret": gs.get("webapp_secret") or "",
        "spreadsheet_id": sid,
        "tab": str(gs.get("tab") or TAB),
    }
    r = requests.post(url, json=body, timeout=90, allow_redirects=True)
    r.raise_for_status()
    j = r.json()
    if not isinstance(j, dict) or j.get("ok") is not True:
        raise RuntimeError(j.get("error") if isinstance(j, dict) else str(j))
    return f"ensure ok: {j.get('result') or j}"
