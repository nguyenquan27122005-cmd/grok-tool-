"""Netflix plugin — sibling folder ../netflix/main.py."""

from __future__ import annotations

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class NetflixToolPlugin(SiblingToolPlugin):
    sibling_dir = "netflix"
    stop_pkg = "nfreg"
    default_mail = "1"
    temp_mails = ("2", "3", "4")
    hotmail_count_mode = "want"
    backends = ("browser", "auto", "protocol")
    default_backend = "browser"
    until_success_default = True

    meta = ToolMeta(
        id="netflix",
        name="Netflix",
        description="Đăng ký Netflix — dừng ở payment · lên Google Sheet",
        icon="N",
        status="ready",
        color="#E50914",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="1",
                options=[
                    FieldOption("1", "Hotmail", "khuyên — Netflix hay chặn temp"),
                    FieldOption("2", "Temp Azpop", ""),
                    FieldOption("3", "Temp tmail", "tmail.wibucrypto.pro"),
                    FieldOption("4", "Temp Guerrilla", ""),
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
                    FieldOption("browser", "Chrome ẩn", "signup wizard, dừng payment"),
                    FieldOption("auto", "Tự động", "HTTP probe rồi Chrome"),
                    FieldOption("protocol", "HTTP probe", "chỉ dò trang public"),
                ],
            ),
            ToolField(
                key="until_success",
                label="Chạy đến khi tới payment",
                type="checkbox",
                default=True,
                hint="need_payment = xong (không thanh toán)",
            ),
        ],
    )

    @staticmethod
    def _classify(status: str) -> str:
        sl = (status or "").strip().lower()
        if sl.startswith("success") or sl == "need_payment":
            return "reg_ok"
        if sl.startswith("stopped") or sl in ("pending", "manual_check"):
            return "pending"
        if sl.startswith("error") or sl:
            return "fail"
        return "other"

    def stats_blurb(self, unique: int, ok: int, fail: int, attempts: int) -> str:
        return f"{unique} email · {ok} tới sheet (success/need_payment) · {fail} fail · {attempts} lượt thử"
