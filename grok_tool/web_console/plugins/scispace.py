"""SciSpace plugin — sibling folder ../Scispace/main.py (reg + checkout links)."""

from __future__ import annotations

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class ScispaceToolPlugin(SiblingToolPlugin):
    sibling_dir = "Scispace"
    stop_pkg = "ssreg"
    default_mail = "0"
    temp_mails = ("0", "2", "3", "4")  # temp đều OK — SciSpace không chặn domain temp
    hotmail_count_mode = "want"
    backends = ("protocol",)
    default_backend = "protocol"
    forced_backend = "protocol"  # HTTP thuần — không có backend browser

    # ── checkout: engine ssreg.checkout ──
    checkout_plan_options = (
        ("premium", "Premium $20/tháng", "1,200 credits/tháng"),
        ("advanced", "Advanced $90/tháng", "10,000 credits/tháng"),
        ("max", "Max $200/tháng", "40,000 credits/tháng"),
        ("team", "Teams (Premium) $25/user/tháng", "tối thiểu 2 users"),
        ("premium,advanced,max", "Cả 3 gói cá nhân", "mỗi acc 3 link"),
    )
    checkout_plan_default = "premium"
    checkout_intervals = ("monthly", "yearly")
    checkout_interval_options = (
        ("monthly", "Monthly (mặc định)", "trả theo tháng — luôn dùng trừ khi bạn đổi"),
        ("yearly", "Yearly", "rẻ hơn 22-40% — chỉ khi bạn chủ động chọn"),
    )

    meta = ToolMeta(
        id="scispace",
        name="SciSpace",
        description="Đăng ký SciSpace — HTTP thuần, không OTP, ~3s/acc · 6 acc ~12s (3 luồng) · lấy link thanh toán",
        icon="📄",
        status="ready",
        color="#5B4CDB",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="0",
                options=[
                    FieldOption("0", "Temp tự chọn", "nhanh nhất — SciSpace không chặn domain temp"),
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
                hint="Mail random@domain được forward về Hotmail trong pool",
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
                key="threads",
                label="Luồng song song",
                type="select",
                default="1",
                options=[
                    FieldOption("1", "1 luồng", "tuần tự — ~3s/acc"),
                    FieldOption("3", "3 luồng", "6 acc ~12s"),
                    FieldOption("5", "5 luồng", "batch lớn — nhanh nhất"),
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
