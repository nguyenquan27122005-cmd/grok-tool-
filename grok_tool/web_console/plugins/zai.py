"""Z.ai plugin — sibling folder ../zai/main.py."""

from __future__ import annotations

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class ZaiToolPlugin(SiblingToolPlugin):
    sibling_dir = "zai"
    stop_pkg = "zaireg"
    # z.ai chặn domain temp (EMAIL_DOMAIN_BLOCKED với guerrilla/azpop) —
    # Hotmail là đường ổn định, default từ 2026-08 sau khi test thật.
    default_mail = "1"
    temp_mails = ("2", "4")
    hotmail_count_mode = "want"
    forced_backend = "protocol"

    meta = ToolMeta(
        id="zai",
        name="Z.ai",
        description="Đăng ký Z.ai / ZCode — HTTP + check quota GLM",
        icon="Z",
        status="ready",
        color="#1F63EC",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="1",
                options=[
                    FieldOption("1", "Hotmail", "pool chung với Grok — z.ai chặn domain temp"),
                    FieldOption("4", "Temp Guerrilla", "z.ai chặn domain — hay fail"),
                    FieldOption("2", "Temp Azpop", "z.ai chặn domain — hay fail"),
                ],
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
                default="protocol",
                options=[
                    FieldOption("protocol", "HTTP không Chrome", "chat.z.ai /auths/signup"),
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
