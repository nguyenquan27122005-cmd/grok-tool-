"""Parse Hotmail / Outlook lines pasted from the web UI or a text file."""
from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def is_email(value: str) -> bool:
    return bool(_EMAIL_RE.match((value or "").strip()))


def is_guid(value: str) -> bool:
    return bool(_GUID_RE.match((value or "").strip()))


def split_line(line: str) -> list[str]:
    raw = (line or "").strip()
    if not raw:
        return []
    if raw.startswith("\ufeff"):
        raw = raw.lstrip("\ufeff").strip()
    if "----" in raw:
        return [p.strip() for p in raw.split("----")]
    if "|" in raw:
        return [p.strip() for p in raw.split("|")]
    if "\t" in raw:
        return [p.strip() for p in raw.split("\t")]
    if "," in raw and "@" in raw.split(",", 1)[0]:
        return [p.strip() for p in raw.split(",")]
    return [raw]


def _looks_token(value: str) -> bool:
    s = (value or "").strip()
    return len(s) >= 40 and not is_guid(s)


def normalize_parts(parts: list[str]) -> dict[str, str] | None:
    """
    Accept:
      email|password|refresh|client_id     (grok_tool)
      email|password|refresh
      email|password
      email----password----client_id----refresh   (register-web)
    """
    parts = [str(p or "").strip() for p in parts]
    while parts and parts[-1] == "":
        parts.pop()
    if len(parts) < 1 or not is_email(parts[0]):
        return None
    email = parts[0]
    password = parts[1] if len(parts) > 1 else ""
    third = parts[2] if len(parts) > 2 else ""
    fourth = parts[3] if len(parts) > 3 else ""
    refresh = ""
    client_id = ""
    if fourth or third:
        if is_guid(third) and (not fourth or _looks_token(fourth) or not is_guid(fourth)):
            client_id, refresh = third, fourth
        elif is_guid(fourth):
            refresh, client_id = third, fourth
        elif _looks_token(third):
            refresh, client_id = third, fourth
        else:
            refresh, client_id = third, fourth
    return {
        "email": email,
        "password": password,
        "refresh": refresh,
        "client_id": client_id,
    }


def format_line(email: str, password: str = "", refresh: str = "", client_id: str = "") -> str:
    return f"{email.strip()}|{password}|{refresh}|{client_id}".rstrip("|")


def parse_hotmail_text(text: str) -> dict[str, Any]:
    """Parse a paste / file dump. Returns {ok, invalid, rows, errors}."""
    rows: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, raw in enumerate((text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        parts = split_line(line)
        rec = normalize_parts(parts)
        if not rec:
            errors.append({"line": i, "text": line[:80], "reason": "Thiếu email hợp lệ"})
            continue
        key = rec["email"].lower()
        if key in seen:
            errors.append({"line": i, "text": rec["email"], "reason": "Trùng trong bản dán"})
            continue
        seen.add(key)
        rec["raw"] = format_line(rec["email"], rec["password"], rec["refresh"], rec["client_id"])
        rows.append(rec)
    return {
        "ok": len(rows),
        "invalid": len(errors),
        "rows": rows,
        "errors": errors[:30],
    }
