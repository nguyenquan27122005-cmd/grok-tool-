"""Canva plugin — sibling folder ../canva/main.py (reg + redeem)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import FieldOption, ToolField, ToolMeta
from .grok import GrokToolPlugin
from .sibling import SiblingToolPlugin


class CanvaToolPlugin(SiblingToolPlugin):
    sibling_dir = "canva"
    stop_pkg = "canreg"
    default_mail = "1"  # Hotmail mặc định
    temp_mails = ("0", "2", "3", "4")
    hotmail_count_mode = "want"
    backends = ("protocol", "auto", "browser")
    default_backend = "browser"

    meta = ToolMeta(
        id="canva",
        name="Canva",
        description="Reg Canva — Hotmail ×5 alias · redeem chỉ OK khi Canva xác nhận gói",
        icon="C",
        status="ready",
        color="#00C4CC",
        fields=[
            ToolField(
                key="job",
                label="Việc",
                type="select",
                default="reg",
                options=[
                    FieldOption("reg", "Reg acc", "Continue with email → OTP"),
                    FieldOption("redeem", "Redeem mã", "Chỉ SUKSES khi trang xác nhận Pro/trial — click nút không đủ"),
                ],
            ),
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="1",
                options=[
                    FieldOption("1", "Hotmail", "1 mail = tối đa 5 acc (+1…+4), OTP về hộp gốc"),
                    FieldOption("3", "Temp tmail.wibu", "0 = hunt thêm 10 domain mới (list cũ giữ). ≥1 = reg trên domain đã OK"),
                    FieldOption("2", "Temp Azpop", "dễ bị INELIGIBLE_EMAIL"),
                    FieldOption("0", "Temp SMART", "azpop ↔ tmail"),
                    FieldOption("4", "Temp Guerrilla", "dễ bị chặn"),
                    FieldOption("5", "Domain riêng", "random@domain — forward về Hotmail pool"),
                ],
            ),
            ToolField(
                key="custom_domain",
                label="Domain riêng",
                type="select",
                default="nguyenquan.dpdns.org",
                options=[
                    FieldOption("nguyenquan.dpdns.org", "nguyenquan.dpdns.org", "Cloudflare Email Routing — khuyên"),
                    FieldOption("quan2712.dedyn.io", "quan2712.dedyn.io", "ImprovMX"),
                ],
                hint="Mail random@domain được forward về Hotmail trong pool — đọc OTP qua Graph",
            ),
            ToolField(
                key="count",
                label="Số lượng",
                type="number",
                default=1,
                min=0,
                max=99,
                hint="Tmail: 0 = hunt tiếp trên web (+10 domain mới hoặc bấm Stop). ≥1 = chỉ reg acc.",
            ),
            ToolField(
                key="backend",
                label="Cách reg",
                type="select",
                default="browser",
                options=[
                    FieldOption("browser", "Chrome ẩn", "OTP xong /templates = acc đã vào"),
                    FieldOption("auto", "HTTP rồi Chrome", "POST 400 thì tự mở Chrome"),
                    FieldOption("protocol", "HTTP rồi Chrome", "giống auto — Canva không cho HTTP-only"),
                ],
            ),
            ToolField(
                key="codes",
                label="Mã redeem",
                type="textarea",
                default="",
                hint="Mỗi dòng 1 mã. Canva từ chối (couldn't redeem) → FAIL, không ghi SUKSES giả.",
            ),
            ToolField(
                key="threads",
                label="Luồng song song",
                type="select",
                default="1",
                options=[
                    FieldOption("1", "1 luồng", "reg ~65s/acc — tuần tự"),
                    FieldOption("2", "2 luồng", "reg ~52s/acc"),
                    FieldOption("3", "3 luồng", "reg ~40s/acc"),
                    FieldOption("4", "4 luồng", "reg ~33s/acc"),
                    FieldOption("5", "5 luồng", "reg ~24s/acc"),
                    FieldOption("6", "6 luồng", "reg ~19s/acc — khuyến nghị"),
                ],
                hint=(
                    "Chọn số Chrome reg chạy cùng lúc — thời gian / 1 acc ghi sẵn ở từng mức. "
                    "6 luồng cần ~2GB RAM + CPU rảnh; máy đang chạy việc nặng thì chọn 4. "
                    "Redeem: Chrome ẩn song song. Canva không làm được HTTP <5s/acc như CapCut (reCAPTCHA Enterprise)."
                ),
            ),
        ],
    )

    def preflight(self, params: dict[str, Any], root: Path) -> None:
        cv = self.sibling_root(root)
        if str(params.get("job") or "reg") == "redeem":
            if not (cv / "main.py").exists():
                raise RuntimeError(f"Thiếu tool Canva: {cv}")
            written = self._write_codes(cv, str(params.get("codes") or ""))
            if written <= 0:
                raise RuntimeError("Thiếu mã redeem — dán mã vào ô Mã redeem (mỗi dòng 1 mã)")
            accs = cv / "data" / "accounts.txt"
            if not accs.exists():
                raise RuntimeError("Thiếu data/accounts.txt — reg acc trước")
            return
        super().preflight(params, root)

    def build_command(self, params: dict[str, Any], root: Path) -> list[str]:
        if str(params.get("job") or "reg") == "redeem":
            py = self._py(root)
            if not py.exists():
                raise RuntimeError(f"Python venv not found: {py}")
            threads = int(params.get("threads") if params.get("threads") is not None else 3)
            threads = max(1, min(8, threads))
            self._write_codes(self.sibling_root(root), str(params.get("codes") or ""))
            return [
                str(py),
                "-u",
                "canva_tool.py",
                "redeem",
                "--accounts",
                "data/accounts.txt",
                "--codes",
                "data/codes_web.txt",
                "--threads",
                str(threads),
                "--output",
                "data/proof.json",
                "--success-only",
            ]
        return super().build_command(params, root)

    @staticmethod
    def _write_codes(cv: Path, raw: str) -> int:
        """Ghi mã từ ô web → data/codes_web.txt. Chấp nhận xuống dòng hoặc dấu phẩy."""
        bits: list[str] = []
        seen: set[str] = set()
        blob = (raw or "").replace(",", "\n").replace(";", "\n")
        for ln in blob.splitlines():
            code = ln.strip()
            if not code or code.startswith("#"):
                continue
            code = code.split()[0]
            key = code.upper()
            if key in seen:
                continue
            seen.add(key)
            bits.append(code)
        dest = cv / "data" / "codes_web.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(("\n".join(bits) + ("\n" if bits else "")), encoding="utf-8")
        return len(bits)

    def hotmail_pool(self, root: Path) -> dict[str, Any]:
        pool = GrokToolPlugin().hotmail_pool(root)
        max_a = 1
        try:
            import json

            cfg = json.loads(
                (self.sibling_root(root) / "config.json").read_text(encoding="utf-8")
            )
            max_a = int(cfg.get("hotmail_max_aliases") or 1)
        except Exception:
            max_a = 1
        pool["max_aliases"] = max(1, max_a)
        try:
            from grokreg.core.config import load_config
            from grokreg.mail.providers import HotmailProvider

            path = GrokToolPlugin()._hotmail_path(root)
            merged = dict(load_config())
            merged["hotmail_max_aliases"] = pool["max_aliases"]
            if path.exists():
                slots, lines = HotmailProvider.from_config(path, merged).available_count()
                pool["slots"] = slots
                pool["lines"] = lines
        except Exception:
            pool["slots"] = int(pool.get("count") or 0)
        return pool

    @staticmethod
    def _classify(status: str) -> str:
        sl = (status or "").strip().lower()
        if sl.startswith("success"):
            return "reg_ok"
        if sl.startswith("redeem:sukses"):
            return "reg_ok"
        if sl.startswith("stopped") or sl in ("pending", "manual_check"):
            return "pending"
        if sl.startswith("error") or sl.startswith("redeem:fail") or sl.startswith("redeem:"):
            return "fail"
        if sl:
            return "fail"
        return "other"

    def parse_results(self, root: Path, limit: int = 200) -> list[dict[str, Any]]:
        cv = self.sibling_root(root)
        path = cv / "data" / "accounts.txt"
        rows: list[dict[str, Any]] = []
        redeem = cv / "data" / "redeem_success.txt"
        if redeem.exists():
            for line in reversed(redeem.read_text(encoding="utf-8", errors="replace").splitlines()):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                parts = s.split("|")
                status = parts[2].strip() if len(parts) > 2 else ""
                ok = status.upper() == "SUKSES"
                rows.append(
                    {
                        "email": parts[0].strip() if parts else "",
                        "password": parts[1].strip() if len(parts) > 1 else "",
                        "status": f"redeem:{status}",
                        "kind": "reg_ok" if ok else "fail",
                        "ok": ok,
                        "tool": "canva",
                    }
                )
                if len(rows) >= limit:
                    return rows
        if not path.exists():
            return rows
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split("|")
            email = parts[0].strip() if parts else ""
            if "@" not in email or any(c.isspace() for c in email):
                continue
            status = parts[2].strip() if len(parts) > 2 else ""
            extra = parts[4].strip() if len(parts) > 4 else (parts[3].strip() if len(parts) > 3 and "|" in s else "")
            if len(parts) > 4:
                extra = "|".join(p.strip() for p in parts[4:] if p.strip())
            elif len(parts) > 3 and not parts[3].strip()[:1].isdigit():
                extra = parts[3].strip()
            kind = self._classify(status)
            rows.append(
                {
                    "email": parts[0].strip() if parts else "",
                    "password": parts[1].strip() if len(parts) > 1 else "",
                    "status": status,
                    "extra": extra,
                    "kind": kind,
                    "ok": kind == "reg_ok",
                    "tool": "canva",
                }
            )
            if len(rows) >= limit:
                break
        return rows
