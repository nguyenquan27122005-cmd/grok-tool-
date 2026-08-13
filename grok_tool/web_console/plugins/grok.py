"""Grok xAI registration plugin — wraps existing main.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .base import BaseToolPlugin, FieldOption, ToolField, ToolMeta


class GrokToolPlugin(BaseToolPlugin):
    meta = ToolMeta(
        id="grok",
        name="Grok / xAI",
        description="Đăng ký Grok — SSO → Sub2API · Google Sheet · ESC stop",
        icon="⚡",
        status="ready",
        color="#229ed9",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="0",
                options=[
                    FieldOption("0", "Temp SMART", "azpop ↔ tmail failover"),
                    FieldOption("1", "Hotmail", "data/hotmails.txt"),
                    FieldOption("2", "Temp azpop only", ""),
                    FieldOption("3", "Temp tmail.wibu only", ""),
                ],
            ),
            ToolField(
                key="count",
                label="Số lượng",
                type="number",
                default=1,
                min=0,
                max=99,
                hint="0 = chạy liên tục đến khi Stop",
            ),
            ToolField(
                key="sub2api",
                label="Auto Sub2API",
                type="checkbox",
                default=True,
                hint="Import SSO/OAuth sau khi reg OK",
            ),
            ToolField(
                key="backend",
                label="Cách reg",
                type="select",
                default="protocol",
                options=[
                    FieldOption("protocol", "HTTP ẩn (nhanh)", "không Chrome signup — cần solver :5072"),
                    FieldOption("auto", "HTTP rồi fallback Chrome ẩn", ""),
                    FieldOption("browser", "Chrome ẩn (off-screen)", "không cướp màn hình"),
                ],
            ),
            ToolField(
                key="hide_chrome",
                label="Ẩn Chrome / không cướp màn hình",
                type="checkbox",
                default=True,
                hint="Cửa sổ reg chạy ngoài màn hình, không nhảy ra trước mặt",
            ),
        ],
    )

    def _py(self, root: Path) -> Path:
        if os.name == "nt":
            return root / "venv" / "Scripts" / "python.exe"
        return root / "venv" / "bin" / "python"

    def build_command(self, params: dict[str, Any], root: Path) -> list[str]:
        py = self._py(root)
        if not py.exists():
            raise RuntimeError(f"Python venv not found: {py}")
        mail = str(params.get("mail") or "0")
        count = int(params.get("count") if params.get("count") is not None else 1)
        count = max(0, min(99, count))
        backend = str(params.get("backend") or "protocol").strip().lower()
        if backend not in ("protocol", "auto", "browser"):
            backend = "protocol"
        return [
            str(py),
            "-u",
            "main.py",
            mail,
            "--count",
            str(count),
            "--backend",
            backend,
        ]

    def cwd(self, root: Path) -> Path:
        return root

    def env_overrides(self, params: dict[str, Any]) -> dict[str, str]:
        env: dict[str, str] = {}
        if params.get("sub2api") is False or str(params.get("sub2api")).lower() in (
            "0",
            "false",
            "no",
            "off",
        ):
            env["GROK_SUB2API"] = "0"
        hide = params.get("hide_chrome", True)
        if hide is False or str(hide).lower() in ("0", "false", "no", "off"):
            env["GROK_NO_FOCUS"] = "0"
        else:
            env["GROK_NO_FOCUS"] = "1"
        return env

    def stop_signal(self, root: Path) -> None:
        stop = root / "data" / "STOP"
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.write_text("stop:web\n", encoding="utf-8")
        try:
            from stop_control import request_stop

            request_stop("web", write_file=True)
        except Exception:
            pass

    @staticmethod
    def _classify(status: str) -> str:
        """Bucket status for stats/UI."""
        st = (status or "").strip()
        sl = st.lower()
        if sl.startswith("added_sub2api"):
            return "sub2api_ok"
        if sl.startswith("success_sub2api"):
            return "reg_ok_sub2_fail"
        if sl == "success" or sl.startswith("success_not_logged"):
            return "reg_ok"
        if sl in ("manual_check", "manual_finish", "stopped"):
            return "pending"
        if sl.startswith("error") or sl:
            return "fail"
        return "other"

    def parse_results(self, root: Path, limit: int = 200) -> list[dict[str, Any]]:
        path = root / "data" / "accounts.txt"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split("|")
            email = parts[0].strip() if parts else ""
            password = parts[1].strip() if len(parts) > 1 else ""
            status = parts[2].strip() if len(parts) > 2 else ""
            kind = self._classify(status)
            ok = kind in ("sub2api_ok", "reg_ok", "reg_ok_sub2_fail")
            rows.append(
                {
                    "email": email,
                    "password": password,
                    "status": status,
                    "kind": kind,
                    "ok": ok,
                    "tool": "grok",
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def _iter_all_rows(self, root: Path) -> list[dict[str, Any]]:
        """All ledger lines oldest→newest (not reversed/limit)."""
        path = root / "data" / "accounts.txt"
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split("|")
            email = parts[0].strip() if parts else ""
            password = parts[1].strip() if len(parts) > 1 else ""
            status = parts[2].strip() if len(parts) > 2 else ""
            kind = self._classify(status)
            out.append(
                {
                    "email": email,
                    "password": password,
                    "status": status,
                    "kind": kind,
                    "ok": kind in ("sub2api_ok", "reg_ok", "reg_ok_sub2_fail"),
                }
            )
        return out

    def stats(self, root: Path) -> dict[str, Any]:
        """
        Clear KPIs (not “weird” success=fail dump):

        - attempts: every line in accounts.txt (mỗi lần thử)
        - unique_emails: số email khác nhau
        - reg_ok: reg xong (success / sub2 ok / sub2 fail nhưng đã reg)
        - sub2api: đã add Sub2API (added_sub2api*)
        - reg_only: reg OK nhưng chưa/không Sub2API
        - sub2_fail: reg OK + Sub2API fail
        - fail: error*
        - pending: manual_check / stopped
        """
        all_rows = self._iter_all_rows(root)
        attempts = len(all_rows)

        # latest status per email (last line wins)
        latest: dict[str, dict[str, Any]] = {}
        for r in all_rows:
            key = (r.get("email") or "").strip().lower()
            if key:
                latest[key] = r

        def count_kind(rows: list[dict[str, Any]], kind: str) -> int:
            return sum(1 for r in rows if r.get("kind") == kind)

        latest_list = list(latest.values())
        # Prefer unique-email latest for “real” account counts
        sub2api = count_kind(latest_list, "sub2api_ok")
        reg_only = count_kind(latest_list, "reg_ok")
        sub2_fail = count_kind(latest_list, "reg_ok_sub2_fail")
        fail = count_kind(latest_list, "fail")
        pending = count_kind(latest_list, "pending")
        reg_ok = sub2api + reg_only + sub2_fail

        # attempt-level (raw lines) for debugging / rate
        att_sub2 = count_kind(all_rows, "sub2api_ok")
        att_reg_ok = sum(1 for r in all_rows if r.get("ok"))
        att_fail = count_kind(all_rows, "fail")

        hotmails = 0
        hp = root / "data" / "hotmails.txt"
        if hp.exists():
            for ln in hp.read_text(encoding="utf-8", errors="ignore").splitlines():
                if ln.strip() and not ln.strip().startswith("#"):
                    hotmails += 1
        counter = 0
        cp = root / "data" / "sub2api_name_counter.json"
        if cp.exists():
            try:
                counter = int(json.loads(cp.read_text(encoding="utf-8")).get("next") or 0)
            except Exception:
                pass

        return {
            # primary KPIs (unique email, last status) — UI shows these
            "total": len(latest),  # unique emails
            "success": reg_ok,  # reg OK (any form)
            "fail": fail,
            "sub2api": sub2api,
            "reg_only": reg_only,
            "sub2_fail": sub2_fail,
            "pending": pending,
            "unique_emails": len(latest),
            # raw ledger
            "attempts": attempts,
            "attempts_success": att_reg_ok,
            "attempts_fail": att_fail,
            "attempts_sub2api": att_sub2,
            "hotmails": hotmails,
            "next_name": f"grok free {max(1, counter):03d}" if counter else "grok free 001",
            # human blurb
            "blurb": (
                f"{len(latest)} email · {reg_ok} reg OK "
                f"({sub2api} Sub2API · {reg_only} reg-only · {sub2_fail} sub2 fail) · "
                f"{fail} fail · {attempts} lượt thử"
            ),
        }
