"""Notion plugin — sibling folder ../notion/main.py (chỉ tmail, không Hotmail)."""

from __future__ import annotations

from typing import Any

from .base import FieldOption, ToolField, ToolMeta
from .sibling import SiblingToolPlugin


class NotionToolPlugin(SiblingToolPlugin):
    sibling_dir = "notion"
    stop_pkg = "notreg"
    supports_hotmail = True  # Domain riêng cần pool Hotmail để đọc OTP forward
    backends = ("browser", "auto", "protocol")
    default_backend = "browser"
    # until_success ON: Notion im lặng chặn nhiều domain tmail (form không
    # chuyển trang) — tự đổi mailbox đến khi reg OK thay vì đốt count.
    # until_offer bao trùm until_success nên để OFF, muốn săn offer thì bật.
    until_success_default = True
    until_offer_default = False

    meta = ToolMeta(
        id="notion",
        name="Notion",
        description="Đăng ký Notion — magic link · offer 1/3/6 tháng · Sheet",
        icon="N",
        status="ready",
        color="#000000",
        fields=[
            ToolField(
                key="mail",
                label="Loại email",
                type="select",
                default="3",
                options=[
                    FieldOption("3", "Temp tmail", "tmail.wibucrypto.pro only"),
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
                hint="0 = đến khi Stop / until-success",
            ),
            ToolField(
                key="backend",
                label="Cách reg",
                type="select",
                default="browser",
                options=[
                    FieldOption("browser", "Chrome ẩn", "notion.so/signup tmail"),
                    FieldOption("auto", "Tự động", "HTTP rồi Chrome nếu fail"),
                    FieldOption("protocol", "HTTP", "sendTemporaryPassword"),
                ],
            ),
            ToolField(
                key="partner",
                label="Partner code (6 tháng)",
                type="text",
                default="",
                hint="Mã Notion for Startups — để trống nếu không có",
            ),
            ToolField(
                key="sheet_all",
                label="Lên sheet cả acc free (không chỉ offer 1/3/6 tháng)",
                type="checkbox",
                default=False,
            ),
            ToolField(
                key="until_success",
                label="Chạy đến khi reg OK (tự đổi mailbox khi domain bị chặn)",
                type="checkbox",
                default=True,
            ),
            ToolField(
                key="until_offer",
                label="Chạy đến khi có offer 1/3/6 tháng",
                type="checkbox",
                default=False,
                hint="3/6 tháng cần company email + website; tmail thường chỉ Free trừ khi form startup ok",
            ),
        ],
    )

    def env_overrides(self, params: dict[str, Any]) -> dict[str, str]:
        env: dict[str, str] = {}
        partner = str(params.get("partner") or "").strip()
        if partner:
            env["NOTION_PARTNER"] = partner
        if params.get("sheet_all") in (True, "1", "true", "yes", "on"):
            env["NOTION_SHEET_ALL"] = "1"
        return env

    def hotmail_pool(self, root: Any) -> dict[str, Any]:
        return {"count": 0, "accounts": [], "slots": 0, "path": ""}

    def import_hotmails(self, root: Any, text: str, mode: str = "append") -> dict[str, Any]:
        raise RuntimeError("Notion chỉ dùng tmail.wibucrypto.pro — không import Hotmail")

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

    def stats_blurb(self, unique: int, ok: int, fail: int, attempts: int) -> str:
        return f"{unique} email · {ok} reg OK · {fail} fail · sheet khi có offer 1/3/6"
