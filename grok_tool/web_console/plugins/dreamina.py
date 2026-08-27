"""Dreamina plugin — sibling folder ../dreamina/main.py (engine Passport CapCut)."""

from __future__ import annotations

from typing import Any

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class DreaminaToolPlugin(SiblingToolPlugin):
    sibling_dir = "dreamina"
    stop_pkg = "capreg"
    default_mail = "4"
    temp_mails = ("2", "4")
    hotmail_count_mode = "all"
    forced_backend = "protocol"  # HTTP Passport — như CapCut

    meta = ToolMeta(
        id="dreamina",
        name="Dreamina",
        description="Đăng ký Dreamina (CapCut AI) — HTTP <5s/acc",
        icon="✦",
        status="ready",
        color="#7C5CFF",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="4",
                options=[
                    FieldOption("4", "Temp Guerrilla", "nhận OTP nhanh"),
                    FieldOption("2", "Temp Azpop", "dự phòng"),
                    FieldOption("1", "Hotmail", "pool chung với Grok — bền nhất"),
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
                default="protocol",
                options=[
                    FieldOption("protocol", "HTTP không Chrome", "Passport ByteDance — ~5s/acc"),
                ],
            ),
            ToolField(
                key="invite",
                label="Mã invite / redeem",
                type="text",
                default="",
                hint="Để trống nếu không có",
            ),
        ],
    )

    def env_overrides(self, params: dict[str, Any]) -> dict[str, str]:
        env: dict[str, str] = {}
        inv = str(params.get("invite") or "").strip()
        if inv:
            env["DREAMINA_INVITE"] = inv
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
