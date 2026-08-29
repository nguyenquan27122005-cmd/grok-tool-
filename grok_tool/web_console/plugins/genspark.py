"""Genspark plugin — sibling folder ../genspark/main.py."""

from __future__ import annotations

from typing import Any

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class GensparkToolPlugin(SiblingToolPlugin):
    sibling_dir = "genspark"
    stop_pkg = "gsparkreg"
    default_mail = "1"
    temp_mails = ()  # chấp nhận mọi mã temp — Genspark hay chặn, vẫn cho chọn
    hotmail_count_mode = "want"
    backends = ("browser", "protocol", "auto", "gpm")
    default_backend = "browser"

    meta = ToolMeta(
        id="genspark",
        name="Genspark",
        description="Đăng ký genspark.ai — B2C CAPTCHA · Hotmail · Claim free month",
        icon="✶",
        status="ready",
        color="#000000",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="1",
                options=[
                    FieldOption("1", "Hotmail", "B2C hay chặn temp — ưu tiên Hotmail"),
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
                    FieldOption("browser", "Chrome ẩn", "Sign up → B2C CAPTCHA + OTP"),
                    FieldOption("gpm", "GPM-Login", "D:\\gpm fingerprint"),
                    FieldOption("auto", "HTTP rồi Chrome", "probe B2C rồi fallback"),
                    FieldOption("protocol", "HTTP", "thường need_browser"),
                ],
            ),
            ToolField(
                key="claim_free_month",
                label="Claim My Free Month",
                type="checkbox",
                default=True,
                hint="Sau login: pricing → Stripe $0 URL (auto-renew sau 30 ngày)",
            ),
        ],
    )

    def env_overrides(self, params: dict[str, Any]) -> dict[str, str]:
        env: dict[str, str] = {}
        claim = params.get("claim_free_month", True)
        if claim is False or str(claim).lower() in ("0", "false", "no", "off"):
            env["GENSPARK_CLAIM"] = "0"
        else:
            env["GENSPARK_CLAIM"] = "1"
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
