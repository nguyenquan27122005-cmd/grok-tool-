"""Claude plugin — sibling folder ../claude/main.py."""

from __future__ import annotations

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class ClaudeToolPlugin(SiblingToolPlugin):
    sibling_dir = "claude"
    stop_pkg = "claudereg"
    default_mail = "1"
    temp_mails = ()  # chấp nhận mọi mã temp — không ép lại (giữ behavior gốc)
    hotmail_count_mode = "want"
    backends = ("browser", "protocol", "auto", "gpm")
    default_backend = "browser"

    meta = ToolMeta(
        id="claude",
        name="Claude / Anthropic",
        description="Đăng ký claude.ai — email OTP · Hotmail · Chrome ẩn",
        icon="✦",
        status="ready",
        color="#D97757",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="1",
                options=[
                    FieldOption("1", "Hotmail", "Anthropic hay chặn temp — ưu tiên Hotmail"),
                    FieldOption("3", "Temp tmail", "dễ bị chặn"),
                    FieldOption("2", "Temp Azpop", "dễ bị chặn"),
                    FieldOption("4", "Temp Guerrilla", "dễ bị chặn"),
                    FieldOption("0", "Temp SMART", "azpop ↔ tmail"),
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
                hint="0 = chạy đến khi Stop",
            ),
            ToolField(
                key="backend",
                label="Cách reg",
                type="select",
                default="browser",
                options=[
                    FieldOption("browser", "Chrome ẩn", "claude.ai/login + OTP"),
                    FieldOption("gpm", "GPM-Login", "D:\\gpm profile gpt — fingerprint, vẫn có thể hỏi SĐT"),
                    FieldOption("auto", "HTTP rồi Chrome", "probe rồi fallback"),
                    FieldOption("protocol", "HTTP", "thường need_browser"),
                ],
            ),
        ],
    )

    @staticmethod
    def _classify(status: str) -> str:
        sl = (status or "").strip().lower()
        if sl.startswith("success"):
            return "reg_ok"
        if sl.startswith("stopped") or sl in ("pending", "manual_check"):
            return "pending"
        if sl.startswith("error") or sl:
            return "fail"
        return "other"
