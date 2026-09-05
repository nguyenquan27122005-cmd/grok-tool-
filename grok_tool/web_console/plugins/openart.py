"""OpenArt plugin — sibling folder ../Openart/main.py (reg + checkout links)."""

from __future__ import annotations

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class OpenartToolPlugin(SiblingToolPlugin):
    sibling_dir = "Openart"
    stop_pkg = "oareg"
    default_mail = "1"
    temp_mails = ("2", "3")  # temp domain bị OpenArt chặn — chỉ để backup
    hotmail_count_mode = "want"
    backends = ("protocol",)
    default_backend = "protocol"
    forced_backend = "protocol"  # Clerk flow thuần HTTP — không có backend browser

    # ── checkout: engine oareg.checkout — POST /api/stripe/subscription ──
    checkout_plan_options = (
        ("starter", "Starter $14/tháng", "4,000 credits/tháng"),
        ("plus", "Plus $34/tháng", "12,000 credits/tháng"),
        ("pro", "Pro $56/tháng", "24,000 credits/tháng"),
        ("wonder", "Wonder $240/tháng", "106,000 credits/tháng"),
        ("starter,plus,pro,wonder", "Cả 4 gói", "mỗi acc 4 link"),
    )
    checkout_plan_default = "starter"
    checkout_intervals = ("month", "year")
    checkout_interval_options = (
        ("month", "Monthly (mặc định)", "trả theo tháng — luôn dùng trừ khi bạn đổi"),
        ("year", "Yearly", "rẻ hơn đến 27% — chỉ khi bạn chủ động chọn"),
    )

    meta = ToolMeta(
        id="openart",
        name="OpenArt",
        description="Đăng ký OpenArt + lấy link thanh toán — HTTP, ~15–30s/acc (prefetch captcha)",
        icon="🎨",
        status="ready",
        color="#FF6154",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="1",
                options=[
                    FieldOption("1", "Hotmail", "pool chung với Grok — OpenArt chặn domain temp"),
                    FieldOption("5", "Domain riêng", "random@domain — forward về Hotmail pool"),
                    FieldOption("2", "Temp Azpop", "backup — domain temp thường bị OpenArt chặn"),
                    FieldOption("3", "Temp tmail", "backup — domain temp thường bị OpenArt chặn"),
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
