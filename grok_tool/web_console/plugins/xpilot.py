"""X-Pilot plugin — sibling folder ../Xpilot/main.py (reg + checkout links)."""

from __future__ import annotations

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class XpilotToolPlugin(SiblingToolPlugin):
    sibling_dir = "Xpilot"
    stop_pkg = "xpreg"
    default_mail = "0"
    temp_mails = ("0", "2", "3", "4")  # temp đều OK — X-Pilot không chặn domain temp
    hotmail_count_mode = "want"
    backends = ("protocol",)
    default_backend = "protocol"
    forced_backend = "protocol"  # HTTP thuần + OTP mail — không có backend browser

    # ── checkout: engine xpreg.checkout ──
    checkout_plan_options = (
        ("creator", "Creator $19/tháng", "tháng $19 · năm $15/tháng"),
        ("pro", "Pro $49/tháng", "tháng $49 · năm $39/tháng"),
        ("ultra", "Ultra $129/tháng", "tháng $129 · năm $103/tháng"),
        ("business", "Business $159/tháng", "tháng $159 · năm $127/tháng — team"),
        ("creator,pro,ultra", "Cả 3 gói cá nhân", "mỗi acc 3 link"),
    )
    checkout_plan_default = "creator"
    checkout_intervals = ("monthly", "yearly")
    checkout_interval_options = (
        ("monthly", "Monthly (mặc định)", "trả theo tháng — luôn dùng trừ khi bạn đổi"),
        ("yearly", "Yearly", "rẻ hơn ~20% — chỉ khi bạn chủ động chọn"),
    )

    meta = ToolMeta(
        id="xpilot",
        name="X-Pilot",
        description="Đăng ký X-Pilot — AI video khóa học — HTTP + OTP mail, ~20–40s/acc · lấy link thanh toán",
        icon="🎬",
        status="ready",
        color="#12A594",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="0",
                options=[
                    FieldOption("0", "Temp tự chọn", "khuyên — X-Pilot không chặn domain temp"),
                    FieldOption("1", "Hotmail", "pool riêng của X-Pilot"),
                    FieldOption("5", "Domain riêng", "random@domain — forward về Hotmail pool"),
                    FieldOption("3", "Temp tmail", "backup"),
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
                    FieldOption("1", "1 luồng", "tuần tự — ~20–40s/acc (chờ OTP)"),
                    FieldOption("3", "3 luồng", "batch nhỏ — nhanh gấp 3"),
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
