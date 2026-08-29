"""Probe hộp thư Hotmail qua Graph — xem mail Genspark OTP có tới không.

Chạy: venv/Scripts/python.exe scripts/probe_hotmail_inbox.py <email>
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests

from grokreg.mail.providers import HotmailProvider

POOL = ROOT / "data" / "hotmails.txt"


def main() -> int:
    email = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if not email:
        print("usage: probe_hotmail_inbox.py <email>")
        return 1

    refresh = ""
    for line in POOL.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and parts[0].lower() == email:
            refresh = parts[2]
            break
    if not refresh:
        print(f"không thấy {email} trong {POOL.name}")
        return 1

    hp = HotmailProvider(POOL)
    token = hp._refresh_access_token(refresh)
    if not token:
        print("không lấy được Graph token (refresh token hết hạn?)")
        return 1

    headers = {"Authorization": f"Bearer {token}"}
    for folder in ("inbox", "junkemail"):
        r = requests.get(
            f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages"
            "?$top=8&$select=subject,from,bodyPreview,receivedDateTime&$orderby=receivedDateTime desc",
            headers=headers, timeout=15,
        )
        msgs = r.json().get("value", [])
        print(f"--- {folder}: {len(msgs)} mail mới nhất ---")
        for m in msgs:
            print(f"  [{m.get('receivedDateTime')}] {str(m.get('subject'))[:60]!r} "
                  f"from={m.get('from', {}).get('emailAddress', {}).get('address', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
