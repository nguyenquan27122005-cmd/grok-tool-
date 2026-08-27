"""CapCut plugin — sibling folder ../capcut/main.py."""

from __future__ import annotations

from typing import Any

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class CapcutToolPlugin(SiblingToolPlugin):
    sibling_dir = "capcut"
    stop_pkg = "capreg"
    default_mail = "4"
    temp_mails = ("2", "4")
    hotmail_count_mode = "all"
    forced_backend = "protocol"  # CapCut chỉ chạy HTTP backend

    meta = ToolMeta(
        id="capcut",
        name="CapCut",
        description="Đăng ký CapCut — HTTP + check ưu đãi Pro/trial",
        icon="✂",
        status="ready",
        color="#00C8D2",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="4",
                options=[
                    FieldOption("4", "Temp Guerrilla", "CapCut gửi OTP được"),
                    FieldOption("2", "Temp Azpop", "thường không nhận mail CapCut"),
                    FieldOption("1", "Hotmail", "pool chung với Grok"),
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
                    FieldOption("protocol", "HTTP không Chrome", "Passport + nhận ưu đãi"),
                ],
            ),
            ToolField(
                key="invite",
                label="Mã invite / redeem",
                type="text",
                default="",
                hint="Để trống nếu không có",
            ),
            ToolField(
                key="claim_offer",
                label="Nhận + check ưu đãi sau reg",
                type="checkbox",
                default=True,
                hint="Login web, thử redeem, đọc Pro/trial/gói/hạn",
            ),
        ],
    )

    def env_overrides(self, params: dict[str, Any]) -> dict[str, str]:
        env: dict[str, str] = {}
        inv = str(params.get("invite") or "").strip()
        if inv:
            env["CAPCUT_INVITE"] = inv
        claim = params.get("claim_offer", True)
        if claim is False or str(claim).lower() in ("0", "false", "no", "off"):
            env["CAPCUT_CLAIM"] = "0"
        else:
            env["CAPCUT_CLAIM"] = "1"
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
