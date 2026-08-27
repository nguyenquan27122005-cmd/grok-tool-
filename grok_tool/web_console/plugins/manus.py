"""Manus plugin — sibling folder ../manus/main.py."""

from __future__ import annotations

from typing import Any

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class ManusToolPlugin(SiblingToolPlugin):
    sibling_dir = "manus"
    stop_pkg = "manreg"
    default_mail = "2"
    temp_mails = ("2", "3", "4")
    hotmail_count_mode = "all"
    backends = ("browser", "protocol", "auto", "gpm")
    default_backend = "browser"
    until_success_default = False

    meta = ToolMeta(
        id="manus",
        name="Manus",
        description="Đăng ký Manus — email OTP · credits · Google Sheet",
        icon="M",
        status="ready",
        color="#34322D",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="2",
                options=[
                    FieldOption("2", "Temp Azpop", "khuyên"),
                    FieldOption("3", "Temp tmail", "tmail.wibucrypto.pro"),
                    FieldOption("1", "Hotmail", "pool chung với Grok"),
                    FieldOption("4", "Temp Guerrilla", ""),
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
                default="browser",
                options=[
                    FieldOption("browser", "Chrome ẩn", "manus.im/login"),
                    FieldOption("gpm", "GPM (anti-detect)", "profile riêng, né Turnstile"),
                    FieldOption("auto", "Tự động", "HTTP rồi Chrome nếu fail"),
                    FieldOption("protocol", "HTTP probe", "dò API công khai"),
                ],
            ),
            ToolField(
                key="invite",
                label="Mã invite",
                type="text",
                default="",
                hint="Mở /invitation/CODE nếu còn hỏi — để trống nếu không",
            ),
            ToolField(
                key="until_success",
                label="Chạy đến khi reg OK",
                type="checkbox",
                default=False,
                hint="SPA hay fail OAuth — bật nếu muốn retry",
            ),
        ],
    )

    def env_overrides(self, params: dict[str, Any]) -> dict[str, str]:
        env: dict[str, str] = {}
        inv = str(params.get("invite") or "").strip()
        if inv:
            env["MANUS_INVITE"] = inv
        return env

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
