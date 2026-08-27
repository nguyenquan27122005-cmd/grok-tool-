"""ChatGPT plugin — sibling folder ../chatgpt (Node script đổi 2FA + mật khẩu).

Khác các tool reg: không reg acc mới — nhận danh sách acc có sẵn
(email|pass|2fa_cu[|pass_moi]), chạy change-2fa.mjs (puppeteer-real-browser),
kết quả ghi data/chatgpt_2fa_moi.txt: email|pass_moi|2fa_cu|2fa_moi.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .base import FieldOption, ToolField, ToolMeta, parse_pipe_accounts
from .sibling import SiblingToolPlugin


class ChatgptToolPlugin(SiblingToolPlugin):
    sibling_dir = "chatgpt"
    stop_pkg = ""  # Node script không đọc STOP — Stop = kill process
    supports_hotmail = False
    supports_resume = False  # không cần field resume/threads tự động

    meta = ToolMeta(
        id="chatgpt",
        name="ChatGPT",
        description=(
            "Đổi 2FA + mật khẩu acc ChatGPT có sẵn — dán list, tool đăng nhập "
            "bằng pass/2FA cũ rồi thay bằng cặp mới"
        ),
        icon="G",
        status="ready",
        color="#10A37F",
        fields=[
            ToolField(
                key="accounts",
                label="Danh sách acc",
                type="textarea",
                default="",
                hint=(
                    "Mỗi dòng: email|pass_cũ|2fa_cũ hoặc email|pass_cũ|2fa_cũ|pass_mới "
                    "(không điền pass_mới thì tool tự sinh). "
                    "Bỏ trống nếu đã nạp list vào chatgpt/data/chatgpt_accounts.txt từ lần trước."
                ),
            ),
        ],
    )

    def preflight(self, params: dict[str, Any], root: Path) -> None:
        cg = self.sibling_root(root)
        if not (cg / "change-2fa.mjs").exists():
            raise RuntimeError(f"Thiếu tool ChatGPT: {cg}")
        if not shutil.which("node"):
            raise RuntimeError("Thiếu Node.js trong PATH — cài Node 18+ để chạy tool này")
        if not (cg / "node_modules" / "puppeteer-real-browser").exists():
            raise RuntimeError("Thiếu node_modules — chạy npm install trong thư mục chatgpt/")
        raw = str(params.get("accounts") or "")
        if self._write_accounts(cg, raw) <= 0:
            existing = cg / "data" / "chatgpt_accounts.txt"
            if not existing.exists() or not existing.read_text(encoding="utf-8", errors="replace").strip():
                raise RuntimeError(
                    "Chưa có acc nào — dán list vào ô Danh sách acc "
                    "(email|pass|2fa_cũ mỗi dòng)"
                )

    def build_command(self, params: dict[str, Any], root: Path) -> list[str]:
        node = shutil.which("node") or "node"
        return [
            node,
            "change-2fa.mjs",
            "--file",
            "data/chatgpt_accounts.txt",
            "--output",
            "data/chatgpt_2fa_moi.txt",
        ]

    def cwd(self, root: Path) -> Path:
        return self.sibling_root(root)

    @staticmethod
    def _write_accounts(cg: Path, raw: str) -> int:
        """Ghi list acc từ ô web → data/chatgpt_accounts.txt (mỗi dòng 1 acc)."""
        rows: list[str] = []
        seen: set[str] = set()
        for ln in (raw or "").splitlines():
            s = ln.strip()
            if not s or s.startswith("#") or "|" not in s:
                continue
            email = s.split("|")[0].strip()
            if "@" not in email or email.lower() in seen:
                continue
            seen.add(email.lower())
            rows.append(s)
        if not rows:
            return 0
        dest = cg / "data" / "chatgpt_accounts.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return len(rows)

    def parse_results(self, root: Path, limit: int = 200) -> list[dict[str, Any]]:
        """Kết quả nằm ở data/chatgpt_2fa_moi.txt: email|pass_mới|2fa_cũ|2fa_mới.

        Dòng chỉ có email (không đủ 4 cột) = acc chưa xử lý xong.
        """
        path = self.sibling_root(root) / "data" / "chatgpt_2fa_moi.txt"
        rows: list[dict[str, Any]] = []
        if not path.exists():
            return rows
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = [p.strip() for p in s.split("|")]
            email = parts[0] if parts else ""
            if "@" not in email:
                continue
            ok = len(parts) >= 4 and bool(parts[3])
            rows.append(
                {
                    "email": email,
                    "password": parts[1] if len(parts) > 1 else "",
                    "status": "2fa_ok" if ok else "chưa xong",
                    "extra": ("2fa_mới: …" + parts[3][-6:]) if parts[3] else "",
                    "kind": "reg_ok" if ok else "fail",
                    "ok": ok,
                    "tool": "chatgpt",
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def stats(self, root: Path) -> dict[str, Any]:
        rows = self.parse_results(root, limit=5000)
        latest: dict[str, dict[str, Any]] = {}
        for r in reversed(rows):
            key = (r.get("email") or "").strip().lower()
            if key:
                latest.setdefault(key, r)
        done = sum(1 for r in latest.values() if r.get("ok"))
        pending = len(latest) - done
        return {
            "total": len(latest),
            "success": done,
            "fail": 0,
            "pending": pending,
            "unique_emails": len(latest),
            "attempts": len(rows),
            "sub2api": 0,
            "reg_only": done,
            "sub2_fail": 0,
            "blurb": f"{len(latest)} acc · {done} đổi 2FA OK · {pending} chờ chạy lại",
        }

    @staticmethod
    def _classify(status: str) -> str:
        return "reg_ok"


# __init_subclass__ của SiblingToolPlugin tự thêm field resume/threads SAU khi
# class tạo xong — tool này chạy Node tuần tự nên lọc bỏ ở đây (module import).
ChatgptToolPlugin.meta.fields = [
    f for f in ChatgptToolPlugin.meta.fields or [] if f.key not in ("resume", "threads")
]
