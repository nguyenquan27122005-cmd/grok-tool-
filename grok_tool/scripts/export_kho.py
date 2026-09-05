# -*- coding: utf-8 -*-
"""export_kho — bơm hàng từ ledger các tool reg sang thư mục kho của shop bot.

Vấn đề: ledger tool là `email|password|status|time|extra` (status ở cột 3),
kho đòi `mail|pass|2fa` (Hotmail: `mail|pass|refresh|client_id`). Copy tay
dễ lọt cột status/rác vào hàng bán. Script này lọc success + chuẩn format.

Chạy (từ D:\\grok_tool\\grok_tool, venv sẵn có):
  python scripts/export_kho.py             # DRY-RUN: chỉ in sẽ xuất gì
  python scripts/export_kho.py --write     # ghi file vào D:\\UserData\\kho
  python scripts/export_kho.py --selftest  # self-check logic, không đụng data

Quy tắc giữ nguyên: script KHÔNG tự nhập kho — người vẫn bấm "nhập kho"
trên Admin UI làm cổng duyệt. File ghi ra là `export_<tool>_<ngày>.txt`,
mỗi email chỉ xuất 1 lần (trừ email đã có sẵn trong folder kho).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

GROK_ROOT = Path(__file__).resolve().parents[2]  # D:\grok_tool
KHO = Path(r"D:\UserData\kho")

# tool folder -> thư mục kho. Tool chưa có danh mục (zai, genspark, manus,
# dreamina) không liệt kê — in cảnh báo khi có hàng mà không có chỗ.
TOOLS = {
    "claude": "Claude",
    "chatgpt": "ChatGPT",
    "canva": "Canva",
    "capcut": "Capcut",
    "Heygen": "Heygen",
    "netflix": "Netflix",
    "notion": "NOTION",
}

# ledger: # comment | email|password|status|time|extra — status ở cột 3.
# status biến thể success* (success_protocol, success_onboarding...) đều tính.
SUCCESS_RE = re.compile(r"^success")
TWO_FA_RE = re.compile(r"^(\d{6,10}|[A-Z2-7=]{16,})$")


def load_success_lines(ledger: Path) -> dict[str, str]:
    """Trả {email: 'mail|pass[|2fa]'} từ ledger — dòng success đầu tiên thắng."""
    out: dict[str, str] = {}
    if not ledger.exists():
        return out
    for raw in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 3 or not SUCCESS_RE.match(parts[2].strip()):
            continue
        email, password = parts[0].strip(), parts[1].strip()
        if not email or not password:
            continue
        extra = parts[4].strip() if len(parts) > 4 else ""
        # Kho chỉ nhận mail|pass|2fa — giữ cột extra CHỈ khi nó trông như 2FA
        # (OTP 6-10 số hoặc base32 TOTP), URL/timestamp là metadata tool.
        fields = [email, password] + ([extra] if TWO_FA_RE.match(extra) else [])
        out.setdefault(email.lower(), "|".join(fields))
    return out


def load_used_hotmail_emails() -> set[str]:
    """Mail hotmail đã NUỐT cho reg (mọi *_used.txt + alias ledger).

    Bán 1 mail đã làm mail-reg là giao OTP quyền sống còn của acc đó cho
    người mua — đây là quy tắc kinh doanh, không phải tuỳ chọn."""
    used: set[str] = set()
    for path in GROK_ROOT.glob("*/data/*used*.txt"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            first = line.strip().split("|", 1)[0].strip().lower()
            if "@" in first:
                used.add(first)
    alias_ledger = GROK_ROOT / "grok_tool" / "data" / "hotmail_aliases.json"
    if alias_ledger.exists():
        try:
            data = json.loads(alias_ledger.read_text(encoding="utf-8", errors="replace"))
            used.update(k.strip().lower() for k in data if "@" in str(k))
        except ValueError:
            pass
    return used


def existing_emails_in_kho(folder: Path) -> set[str]:
    """Email đã nằm trong folder kho (mọi file .txt) — tránh xuất trùng."""
    have: set[str] = set()
    if not folder.exists():
        return have
    for path in folder.glob("*.txt"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            first = line.strip().split("|", 1)[0].strip().lower()
            if "@" in first:
                have.add(first)
    return have


def export_account_tools(write: bool) -> int:
    total = 0
    for tool, category in sorted(TOOLS.items()):
        lines = load_success_lines(GROK_ROOT / tool / "data" / "accounts.txt")
        folder = KHO / category
        fresh = {e: l for e, l in lines.items() if e not in existing_emails_in_kho(folder)}
        status = f"{len(fresh)} mới / {len(lines)} success"
        if write and fresh:
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = folder / f"export_{tool}_{stamp}.txt"
            out.write_text("\n".join(fresh.values()) + "\n", encoding="utf-8")
            status += f" -> {out.name}"
        print(f"  {tool:10s} -> kho/{category:12s} {status}")
        total += len(fresh)
    return total


def export_hotmail(write: bool) -> int:
    pool = GROK_ROOT / "grok_tool" / "data" / "hotmails.txt"
    used = load_used_hotmail_emails()
    have = existing_emails_in_kho(KHO / "Hotmail")
    fresh: list[str] = []
    for raw in pool.read_text(encoding="utf-8", errors="replace").splitlines() if pool.exists() else []:
        line = raw.strip()
        email = line.split("|", 1)[0].strip().lower()
        if line and "@" in email and email not in used and email not in have:
            fresh.append(line)
    print(f"  hotmail   -> kho/Hotmail      {len(fresh)} mới "
          f"({len(used)} đã dùng cho reg bị loại)")
    if write and fresh:
        folder = KHO / "Hotmail"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = folder / f"export_hotmail_{stamp}.txt"
        out.write_text("\n".join(fresh) + "\n", encoding="utf-8")
    return len(fresh)


def selftest() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "accounts.txt"
        ledger.write_text(
            "# email|password|status|time\n"
            "a@x.com|p1|success|2026-09-01|https://meta\n"   # extra=URL -> bỏ cột
            "b@x.com|p2|success|2026-09-01|748291\n"          # extra=OTP 6 số -> giữ
            "c@x.com|p3|error:otp_timeout|2026-09-01|\n"      # fail -> bỏ
            "a@x.com|p4|success|2026-09-02|\n"                # trùng email -> bỏ
            "d@x.com|p5|success_protocol|2026-09-01|\n",      # success* -> nhận
            encoding="utf-8",
        )
        got = load_success_lines(ledger)
        assert list(got) == ["a@x.com", "b@x.com", "d@x.com"], got
        assert got["a@x.com"] == "a@x.com|p1", got["a@x.com"]
        assert got["b@x.com"] == "b@x.com|p2|748291", got["b@x.com"]
        assert got["d@x.com"] == "d@x.com|p5", got["d@x.com"]

        used_file = Path(tmp) / "t1" / "data" / "hotmails_used.txt"
        used_file.parent.mkdir(parents=True)
        used_file.write_text("u1@hotmail.com|p|r|c\n", encoding="utf-8")
        old = load_used_hotmail_emails.__globals__["GROK_ROOT"]
        load_used_hotmail_emails.__globals__["GROK_ROOT"] = Path(tmp)
        try:
            used = load_used_hotmail_emails()
            assert "u1@hotmail.com" in used, used
        finally:
            load_used_hotmail_emails.__globals__["GROK_ROOT"] = old
    print("OK selftest: filter success, 2FA, dedupe, used-mailbox")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Export ledger tool reg -> kho shop bot")
    ap.add_argument("--write", action="store_true", help="ghi file (mặc định dry-run)")
    ap.add_argument("--selftest", action="store_true", help="chạy self-check rồi thoát")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    print(f"KHO={KHO}  mode={'GHI FILE' if args.write else 'DRY-RUN (--write để ghi)'}")
    n = export_account_tools(args.write) + export_hotmail(args.write)
    print(f"\nTổng dòng mới sẽ có trong kho: {n}"
          + ("" if args.write else "  (chưa ghi gì — xem xong chạy lại với --write)"))
    print("Sau đó: Admin UI -> nhập kho như thường (cổng duyệt của người).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
