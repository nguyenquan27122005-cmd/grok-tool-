"""Push OpenArt success ledger → Google Sheet tab `openart` (same layout as grok)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_log = logging.getLogger(__name__)

from oareg.paths import DATA, GROK_ROOT, ROOT

ACCOUNTS = DATA / "accounts.txt"


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
    gs.setdefault("tab", "openart")
    gs["tab"] = "openart"
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


def parse_success_accounts() -> list[dict[str, str]]:
    if not ACCOUNTS.exists():
        return []
    by_email: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for ln in ACCOUNTS.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = ln.strip()
        if not ln or "|" not in ln:
            continue
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 3:
            continue
        email, password, status = parts[0], parts[1], parts[2]
        ts = parts[3] if len(parts) >= 4 else ""
        em = email.lower()
        if not em or "@" not in em:
            continue
        if em not in by_email:
            order.append(em)
        by_email[em] = {
            "email": email,
            "password": password,
            "status": status,
            "ts": ts,
        }
    out: list[dict[str, str]] = []
    for em in order:
        r = by_email[em]
        if str(r.get("status") or "").lower().startswith("success"):
            out.append(r)
    return out


def build_payload() -> dict[str, Any]:
    rows = parse_success_accounts()
    cfg = _load_json(ROOT / "config.json")
    password = str(cfg.get("fixed_password") or "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vpn = "—"
    try:
        if GROK_ROOT.is_dir():
            import sys

            if str(GROK_ROOT) not in sys.path:
                sys.path.insert(0, str(GROK_ROOT))
            from grokreg.delivery.gsheets_export import detect_exit_ip_country

            vpn = detect_exit_ip_country().get("label") or "—"
    except Exception as e:
        _log.warning("detect_exit_ip_country fail: %s — sheet ghi VPN '—'", e)
    accounts: list[list[Any]] = []
    for n, r in enumerate(rows, 1):
        accounts.append(
            [
                n,
                "FULL",
                r.get("email", ""),
                r.get("password", ""),
                r.get("status", "") or "success",
                r.get("status", ""),
                (r.get("ts") or "")[:10],
                r.get("ts") or "—",
                vpn,
            ]
        )
    return {
        "tab": "openart",
        "mode": "success_ledger",
        "summary": {
            "exported_at": now,
            "password_common": password,
            "alltime_full": len(rows),
            "vpn_label": vpn,
        },
        "accounts": accounts,
        "fails": [],
    }


def _post(gs: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    url = str(gs.get("webapp_url") or "").strip()
    sid = str(gs.get("spreadsheet_id") or "").strip()
    if not url or not sid:
        raise RuntimeError("Thiếu webapp_url / spreadsheet_id")
    body = dict(payload)
    body["secret"] = gs.get("webapp_secret") or ""
    body["spreadsheet_id"] = sid
    body["tab"] = "openart"
    r = requests.post(url, json=body, timeout=90, allow_redirects=True)
    if r.status_code >= 400:
        raise RuntimeError(f"webapp HTTP {r.status_code}: {r.text[:300]}")
    try:
        j = r.json()
    except ValueError as e:
        raise RuntimeError(f"webapp non-JSON: {r.text[:200]}") from e
    if not isinstance(j, dict) or j.get("ok") is not True:
        raise RuntimeError(j.get("error") if isinstance(j, dict) else str(j))
    return j


def append_openart_account(
    email: str,
    password: str,
    status: str,
    ts: str = "",
) -> str:
    """Một acc thành công → 1 dòng trên tab openart (không ghi đè cả bảng)."""
    gs = load_gs_config()
    if not gs.get("enabled", True):
        return "google_sheets disabled"
    j = _post(
        gs,
        {
            "action": "append",
            "account": {
                "email": email,
                "password": password,
                "name": status or "success",
                "status": status,
                "time": ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "vpn": "—",
            },
        },
    )
    return f"append ok: {j.get('result') or j}"


def export_openart_to_sheet() -> str:
    gs = load_gs_config()
    if not gs.get("enabled", True):
        return "google_sheets disabled"
    payload = build_payload()
    j = _post(gs, payload)
    return f"webapp ok: {j}"


def push_checkout_links(rows: list[dict[str, str]]) -> str:
    """Đẩy link checkout vào tab `<tool>_checkout` (action append_checkout của Apps Script).

    Yêu cầu Apps Script đã update source mới (có action append_checkout).
    rows: [{email, plan, interval, url, ts}]
    """
    gs = load_gs_config()
    url = str(gs.get("webapp_url") or "").strip()
    sid = str(gs.get("spreadsheet_id") or "").strip()
    if not url or not sid:
        raise RuntimeError("Thiếu webapp_url / spreadsheet_id trong google_sheets config")
    body = {
        "action": "append_checkout",
        "tab": "openart",
        "secret": gs.get("webapp_secret") or "",
        "spreadsheet_id": sid,
        "rows": rows,
    }
    r = requests.post(url, json=body, timeout=90, allow_redirects=True)
    if r.status_code >= 400:
        raise RuntimeError(f"webapp HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    if not isinstance(j, dict) or j.get("ok") is not True:
        raise RuntimeError(j.get("error") if isinstance(j, dict) else str(j))
    res = j.get("result") or {}
    return f"push ok: tab={res.get('tab')} added={res.get('added')}"


if __name__ == "__main__":
    print(export_openart_to_sheet())
