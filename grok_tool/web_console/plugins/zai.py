"""Z.ai plugin — sibling folder ../zai/main.py."""

from __future__ import annotations

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class ZaiToolPlugin(SiblingToolPlugin):
    sibling_dir = "zai"
    stop_pkg = "zaireg"
    # z.ai chặn domain temp (EMAIL_DOMAIN_BLOCKED với guerrilla/azpop) — chỉ
    # Hotmail. forced_mail nên web không còn select loại email.
    forced_mail = "1"
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
