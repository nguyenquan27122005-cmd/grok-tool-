#!/usr/bin/env python3
"""
Scan files for secrets before git push.

Usage:
  python scripts/check_no_secrets.py
  python scripts/check_no_secrets.py --staged

Exit 1 if unsafe.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git_toplevel() -> Path:
    """Repo root từ git — đáng tin hơn giả định thư mục đứng.

    Chạy `git rev-parse --show-toplevel` để luôn ra đúng nơi có .git,
    bất kể script được gọi từ đâu trong repo.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, errors="replace", timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except Exception:
        pass
    return ROOT


def _scan_base(staged: bool) -> Path:
    """Thư mục gốc để resolve relative path khi scan.

    - staged: dùng git repo top-level — `git diff --cached --name-only`
      trả path tương đối với repo root (script hiện/trước đây dán 1 cấp →
      sai khi repo root ≠ thư mục chứa file này).
    - không staged: quét nguyên cây của package (ROOT = grok_tool/).
    """
    return _git_toplevel() if staged else ROOT

BLOCKED_NAMES = {
    "config.json",
    "accounts.txt",
    "hotmails.txt",
    "hotmails_used.txt",
    "gsheets_service_account.json",
    "delivery_queue.json",
    "gsheet_last_payload.json",
    "vpn_by_email.json",
    "setup_state.json",
    "gsheets_push_once.gs",
    ".env",
}

# High-signal content (avoid matching normal code like password=session.password)
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r'(?i)["\'](?:password|passwd|fixed_password|sub2api_pass|webapp_secret|'
            r'api_token|api_key|client_secret|refresh_token)["\']\s*:\s*["\']'
            r'(?!YOUR_|CHANGE_ME|PLACEHOLDER|xxx|TODO|\{password\}|\{|password|secret|"")'
            r'[^"\']{5,}["\']'
        ),
        "json secret field",
    ),
    (
        re.compile(
            r"(?i)(?:fixed_password|sub2api_pass|webapp_secret|api_token)\s*=\s*"
            r'["\'](?!YOUR_|CHANGE_ME)[^"\']{6,}["\']'
        ),
        "assigned secret",
    ),
    (
        re.compile(r"https://script\.google\.com/macros/s/[A-Za-z0-9_\-]{20,}/exec"),
        "Apps Script webapp URL",
    ),
    (
        re.compile(
            r'(?i)["\']spreadsheet_id["\']\s*:\s*["\'][A-Za-z0-9_\-]{30,}["\']'
        ),
        "spreadsheet id",
    ),
    (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "private key",
    ),
    (
        # ledger email|password|status — bỏ qua domain example reserved (RFC 2606)
        re.compile(
            r"(?i)[A-Za-z0-9._%+\-]+@(?!example\.)(?!.*\.test)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\s*\|[^\n|]{6,}\|"
        ),
        "email|password|status ledger line",
    ),
    (
        re.compile(r'(?i)"password_common"\s*:\s*"[^"]{4,}"'),
        "password_common dump",
    ),
]

SKIP_SUFFIX = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".pyc",
    ".pma",
    ".bin",
    ".md",
}
SKIP_DIRS = {
    "venv",
    ".git",
    "chrome_profile_v3",
    "__pycache__",
    "node_modules",
    ".grok",
}

# Files that may mention secrets as documentation only
ALLOWLIST_NAMES = {
    "check_no_secrets.py",
    "config.example.json",
    "SAFE_GITHUB.md",
}


def _is_gitignored(rel: str, base: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=base,
            capture_output=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def list_files(staged: bool) -> list[Path]:
    base = _scan_base(staged)
    if staged:
        try:
            out = subprocess.check_output(
                ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                cwd=base,
                text=True,
                errors="replace",
            )
            return [base / p.strip() for p in out.splitlines()
                    if p.strip() and (base / p.strip()).is_file()]
        except Exception as e:
            print(f"[warn] staged list failed: {e}")
    files: list[Path] = []
    has_git = Path(base / ".git").is_dir()
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        parts = set(p.relative_to(base).parts)
        if parts & SKIP_DIRS:
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        rel = p.relative_to(base).as_posix()
        if rel.startswith("data/") and p.name not in (".gitkeep", "README.md"):
            continue
        if "chrome_profile" in rel:
            continue
        if p.name in ALLOWLIST_NAMES:
            files.append(p)
            continue
        # local secrets stay local
        if p.name in BLOCKED_NAMES or rel == "config.json":
            continue
        if has_git and _is_gitignored(rel, base):
            continue
        # also skip paths that match our gitignore intent even without git
        if rel.endswith("setup_state.json") or rel.endswith("gsheets_push_once.gs"):
            continue
        files.append(p)
    return files


def is_blocked_path(p: Path, base: Path) -> str | None:
    try:
        rel = p.relative_to(base).as_posix()
    except ValueError:
        rel = p.name  # ngoài base → so theo tên để không bỏ sót
    if p.name in BLOCKED_NAMES:
        return f"blocked name: {p.name}"
    if rel.endswith("config.json"):
        return "use config.example.json only"
    if ("/data/" in rel or rel.startswith("data/")) and p.name not in (".gitkeep", "README.md"):
        return "data/ is local-only"
    if "service_account" in p.name.lower() or p.name.startswith("client_secret"):
        return "credential file"
    if rel.endswith("setup_state.json") or rel.endswith("gsheets_push_once.gs"):
        return "local sheet dump / webapp state"
    return None


def scan_content(p: Path) -> list[str]:
    if p.name in ALLOWLIST_NAMES or p.name.endswith(".example.json"):
        return []
    hits: list[str] = []
    try:
        if p.stat().st_size > 3_000_000:
            return ["file too large to scan safely"]
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    for rx, label in PATTERNS:
        if rx.search(text):
            hits.append(label)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    args = ap.parse_args()

    files = list_files(staged=args.staged)
    base = _scan_base(args.staged)
    problems: list[str] = []

    for p in files:
        try:
            rel = p.relative_to(base).as_posix()
        except ValueError:
            rel = p.name
        br = is_blocked_path(p, base)
        if br:
            problems.append(f"BLOCK  {rel}  ({br})")
            continue
        for h in scan_content(p):
            problems.append(f"SECRET {rel}  (~{h})")

    print(f"Scanned {len(files)} file(s)  staged={args.staged}")
    if problems:
        print("\n*** UNSAFE — do NOT push ***\n")
        for line in problems[:60]:
            print(" ", line)
        if len(problems) > 60:
            print(f"  ... +{len(problems) - 60} more")
        print("\nSee SAFE_GITHUB.md")
        return 1
    print("OK — no obvious secrets in files that would be published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
