"""Base class cho các plugin shell-out sang thư mục engine ngang hàng.

Một plugin = khai báo thuộc tính (thư mục, package stop, mail options,
backends, cờ until…) + `_classify`. Toàn bộ logic chung (build lệnh,
preflight pool Hotmail, STOP signal, parse ledger, stats) nằm ở đây.

Ma trận khác biệt giữa các tool (chốt bằng golden test
tests/test_plugins_golden.py):
- mail: forced (notion="3") / validate theo temp_mails / giữ nguyên (claude)
- count Hotmail: "all" (slots, cap 2000) hoặc "want" (min(want, slots, 99))
- backend: forced (capcut/zai="protocol") hoặc validate theo backends
- until-success default: None (không có cờ) / True (netflix, notion) / False (manus)
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

from .base import BaseToolPlugin, FieldOption, ToolField, parse_pipe_accounts
from .grok import GrokToolPlugin

logger = logging.getLogger(__name__)


class SiblingToolPlugin(BaseToolPlugin):
    # ── khai báo bắt buộc ──
    sibling_dir: str = ""        # thư mục engine ở repo gốc (VD "netflix")
    stop_pkg: str = ""           # package chứa stop.py (VD "nfreg")

    # ── mail ──
    default_mail: str = "1"
    temp_mails: Tuple[str, ...] = ()   # rỗng = chấp nhận mọi mã temp (claude)
    forced_mail: Optional[str] = None  # đặt = luôn dùng mã này (notion "3")
    supports_hotmail: bool = True
    # Mã "5" = Domain riêng (random@domain → forward về Hotmail pool, đọc qua Graph)
    CUSTOM_MAIL = "5"

    # ── count ──
    hotmail_count_mode: str = "want"   # "all" | "want"

    # ── backend ──
    backends: Tuple[str, ...] = ()
    default_backend: str = "browser"
    forced_backend: Optional[str] = None  # capcut/zai ép "protocol"

    # ── cờ until ──
    until_success_default: Optional[bool] = None  # None = không có cờ
    until_offer_default: Optional[bool] = None

    # ── resume/checkpoint ──
    supports_resume: bool = True

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        meta = getattr(cls, "meta", None)
        if meta is None:
            return
        if cls.supports_resume and not any(f.key == "resume" for f in (meta.fields or [])):
            meta.fields.append(
                ToolField(
                    key="resume",
                    label="Resume batch cũ",
                    type="checkbox",
                    default=False,
                    hint="Bật để chạy tiếp batch chưa xong (checkpoint data/batch_state.json) thay vì batch mới",
                )
            )
        if not any(f.key == "threads" for f in (meta.fields or [])):
            meta.fields.append(
                ToolField(
                    key="threads",
                    label="Luồng song song",
                    type="select",
                    default="1",
                    options=[
                        FieldOption("1", "1 luồng", "tuần tự — an toàn nhất"),
                        FieldOption("2", "2 luồng", "2 acc cùng lúc — chỉ backend HTTP, batch số lượng cố định"),
                    ],
                )
            )
        # Chỉ tool nào có option mail "5" (Domain riêng) mới cần chọn Hotmail đọc OTP
        mail_field = next((f for f in (meta.fields or []) if f.key == "mail"), None)
        has_custom = bool(
            mail_field
            and any(str(o.value) == cls.CUSTOM_MAIL for o in (mail_field.options or []))
        )
        if has_custom and not any(f.key == "custom_read_mailbox" for f in (meta.fields or [])):
            meta.fields.append(
                ToolField(
                    key="custom_read_mailbox",
                    label="Hotmail đọc OTP",
                    type="select",
                    default="auto",
                    options=[
                        FieldOption("auto", "Tự động — đầu pool", "mặc định"),
                    ],
                    hint=(
                        "Mail domain riêng được forward về 1 Hotmail CỐ ĐỊNH — chọn đúng "
                        "acc đó trong pool để đọc OTP. Không thấy acc? Thêm vào "
                        "data/hotmails.txt (có refresh_token) trước."
                    ),
                )
            )

    def sibling_root(self, root: Path) -> Path:
        return root.parent / self.sibling_dir

    def proxy_config_path(self, root: Path) -> Path | None:
        # 8 tool sibling đều đọc key "proxy" trong config.json của mình
        return self.sibling_root(root) / "config.json"

    def _py(self, root: Path) -> Path:
        from grokreg.core import winhide

        return winhide.hidden_python(root)

    @staticmethod
    def _is_hotmail_mail(mail: str) -> bool:
        return GrokToolPlugin._is_hotmail_mail(mail)

    # ── lifecycle ──

    def preflight(self, params: dict[str, Any], root: Path) -> None:
        d = self.sibling_root(root)
        if not (d / "main.py").exists():
            raise RuntimeError(f"Thiếu tool {self.meta.name}: {d}")
        if not self.supports_hotmail:
            return
        mail = self.forced_mail or str(params.get("mail") or self.default_mail)
        if not self._is_hotmail_mail(mail) and mail != self.CUSTOM_MAIL:
            return
        pool = self.hotmail_pool(root)
        slots = int(pool.get("slots") or pool.get("count") or 0)
        if slots <= 0:
            raise RuntimeError("Pool Hotmail trống / hết slot alias — import acc rồi Start")

    def _apply_custom_read_mailbox(self, params: dict[str, Any], root: Path) -> None:
        """Ghi custom_read_mailbox vào config.json của grok_tool — mọi engine
        sibling merge config này nên tự đọc đúng Hotmail đích khi mail=5."""
        if str(params.get("mail") or "") != self.CUSTOM_MAIL:
            return
        mb = str(params.get("custom_read_mailbox") or "").strip()
        if not mb or mb.lower() == "auto":
            return
        try:
            import json

            cfg_path = Path(root) / "config.json"
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            if str(raw.get("custom_read_mailbox") or "") != mb:
                raw["custom_read_mailbox"] = mb
                cfg_path.write_text(
                    json.dumps(raw, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                logger.info("custom_read_mailbox=%s ghi vào %s", mb, cfg_path)
        except Exception as e:
            logger.warning("custom_read_mailbox write fail: %s", e)

    def build_command(self, params: dict[str, Any], root: Path) -> list[str]:
        py = self._py(root)
        if not py.exists():
            raise RuntimeError(f"Python venv not found: {py}")
        self._apply_custom_read_mailbox(params, root)
        mail, count = self._resolve_mail_count(params, root)
        if self.forced_backend:
            backend = self.forced_backend
        else:
            backend = str(params.get("backend") or self.default_backend).strip().lower()
            if backend not in self.backends:
                backend = self.default_backend
        cmd = [str(py), "-u", "main.py", mail, "--count", str(count), "--backend", backend]
        if mail == self.CUSTOM_MAIL:
            domain = str(params.get("custom_domain") or "nguyenquan.dpdns.org").strip().lstrip("@")
            cmd += ["--custom-domain", domain]
        cmd.extend(self._until_flags(params))
        if params.get("resume") in (True, "1", "true", "yes", "on"):
            cmd.append("--resume")
        th = str(params.get("threads") or "1").strip()
        if th.isdigit() and 2 <= int(th) <= 8:
            cmd += ["--threads", th]
        return cmd

    def _resolve_mail_count(self, params: dict[str, Any], root: Path) -> tuple[str, int]:
        mail = self.forced_mail or str(params.get("mail") or self.default_mail)
        if self.forced_mail is None and not self._is_hotmail_mail(mail):
            if self.temp_mails and mail not in self.temp_mails and mail != self.CUSTOM_MAIL:
                mail = self.default_mail
        want = int(params.get("count") if params.get("count") is not None else 1)
        if self.supports_hotmail and self._is_hotmail_mail(mail):
            pool = self.hotmail_pool(root)
            slots = int(pool.get("slots") or pool.get("count") or 0)
            if slots <= 0:
                raise RuntimeError("Pool Hotmail trống — import acc trước khi Start")
            if self.hotmail_count_mode == "all":
                return mail, min(slots, 2000)
            return mail, (slots if want <= 0 else min(max(1, want), slots, 99))
        return mail, max(0, min(99, want))

    def _until_flags(self, params: dict[str, Any]) -> list[str]:
        flags: list[str] = []
        if self.until_success_default is not None:
            v = params.get("until_success", self.until_success_default)
            if self.until_success_default is True:
                on = v not in (False, "0", "false", "no", "off")
            else:
                on = v in (True, "1", "true", "yes", "on")
            if on:
                flags.append("--until-success")
        if self.until_offer_default is not None:
            v = params.get("until_offer", self.until_offer_default)
            if v in (True, "1", "true", "yes", "on"):
                flags.append("--until-offer")
        return flags

    def cwd(self, root: Path) -> Path:
        return self.sibling_root(root)

    def stop_signal(self, root: Path) -> None:
        stop = self.sibling_root(root) / "data" / "STOP"
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.write_text("stop:web\n", encoding="utf-8")
        try:
            d = str(self.sibling_root(root))
            if d not in sys.path:
                sys.path.insert(0, d)
            mod = importlib.import_module(f"{self.stop_pkg}.stop")
            mod.request_stop("web", write_file=True)
        except Exception:
            pass

    # ── hotmail pool (chung với Grok) ──

    def hotmail_pool(self, root: Path) -> dict[str, Any]:
        return GrokToolPlugin().hotmail_pool(root)

    def import_hotmails(self, root: Path, text: str, mode: str = "append") -> dict[str, Any]:
        return GrokToolPlugin().import_hotmails(root, text, mode)

    # ── ledger ──

    @staticmethod
    def _classify(status: str) -> str:
        raise NotImplementedError

    def parse_results(self, root: Path, limit: int = 200) -> list[dict[str, Any]]:
        return parse_pipe_accounts(
            self.sibling_root(root) / "data" / "accounts.txt",
            tool=self.meta.id,
            classify=self._classify,
            limit=limit,
        )

    def stats(self, root: Path) -> dict[str, Any]:
        rows = list(reversed(self.parse_results(root, limit=5000)))
        latest: dict[str, dict[str, Any]] = {}
        for r in rows:
            key = (r.get("email") or "").strip().lower()
            if key:
                latest[key] = r
        latest_list = list(latest.values())
        ok = sum(1 for r in latest_list if r.get("ok"))
        fail = sum(1 for r in latest_list if r.get("kind") == "fail")
        pending = sum(1 for r in latest_list if r.get("kind") == "pending")
        return {
            "total": len(latest),
            "success": ok,
            "fail": fail,
            "pending": pending,
            "unique_emails": len(latest),
            "attempts": len(rows),
            "sub2api": 0,
            "reg_only": ok,
            "sub2_fail": 0,
            "blurb": self.stats_blurb(len(latest), ok, fail, len(rows)),
        }

    def stats_blurb(self, unique: int, ok: int, fail: int, attempts: int) -> str:
        return f"{unique} email · {ok} reg OK · {fail} fail · {attempts} lượt thử"
