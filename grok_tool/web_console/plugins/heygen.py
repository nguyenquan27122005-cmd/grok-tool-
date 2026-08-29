"""Heygen plugin — sibling folder ../Heygen/main.py."""

from __future__ import annotations

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class HeygenToolPlugin(SiblingToolPlugin):
    sibling_dir = "Heygen"
    stop_pkg = "heyreg"
    default_mail = "2"
    temp_mails = ("2", "3")  # mọi mã temp khác (0/tmail…) → về azpop "2"
    hotmail_count_mode = "all"
    backends = ("protocol", "auto", "browser")
    # Protocol cần solver giải Turnstile của HeyGen (thường fail) — browser là
    # đường ổn định, default từ 2026-08 sau khi test thật.
    default_backend = "browser"

    meta = ToolMeta(
        id="heygen",
        name="HeyGen",
        description="Đăng ký HeyGen — magic link → Google Sheet",
        icon="▶",
        status="ready",
        color="#14b8a6",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="2",
                options=[
                    FieldOption("3", "Temp tmail", "tự ban domain hỏng sau mỗi lần fail — càng chạy càng chuẩn"),
                    FieldOption("2", "Temp Azpop", "nhanh — nếu mail không tới, tự retry bằng Hotmail"),
                    FieldOption("1", "Hotmail", "pool chung với Grok — mail đến chắc nhất"),
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
                hint="0 = chạy liên tục đến khi Stop",
            ),
            ToolField(
                key="backend",
                label="Cách reg",
                type="select",
                default="browser",
                options=[
                    FieldOption("browser", "Chrome ẩn", "đường ổn định — qua Turnstile trên form thật"),
                    FieldOption("protocol", "HTTP không Chrome", "cần solver :5072 giải Turnstile HeyGen"),
                    FieldOption("auto", "Tự động", "HTTP rồi Chrome nếu fail"),
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
