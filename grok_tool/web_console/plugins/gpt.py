"""GPT / OpenAI tool — chạy web app GPT-TOOL (../gpt-tool) tại :8083.

GPT-TOOL là web console riêng (Reg ChatGPT/Codex, UPI QR, payment link).
Plugin này khởi động service như một job dài hạn của Draco Reg console:
Start = bật web, Stop = tắt, log stream trong console, UI gốc mở ở
http://127.0.0.1:8083.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseToolPlugin, ToolField, ToolMeta


class GptToolPlugin(BaseToolPlugin):
    # Chọn tile ở #/register → console tự mở web GPT-TOOL (:8083)
    external_url = "http://127.0.0.1:8083/"

    meta = ToolMeta(
        id="openai",
        name="GPT / OpenAI",
        description="Reg ChatGPT/Codex đầy đủ — chọn để mở GPT-TOOL :8083",
        icon="◎",
        status="ready",
        color="#10A37F",
        fields=[
            ToolField(
                key="port",
                label="Port web",
                type="text",
                default="8083",
                hint="Start để bật service, rồi bấm 'Mở GPT-TOOL ↗'",
            ),
        ],
    )

    @staticmethod
    def gpt_root(root: Path) -> Path:
        return root.parent / "gpt-tool"

    def _py(self, root: Path) -> Path:
        venv = self.gpt_root(root) / ".venv" / "Scripts"
        for name in ("python.exe", "pythonw.exe"):
            cand = venv / name
            if cand.is_file():
                return cand
        # chưa setup venv — dùng venv chính (có thể thiếu dependency)
        from grokreg.core import winhide

        return winhide.hidden_python(root)

    def preflight(self, params: dict[str, Any], root: Path) -> None:
        gr = self.gpt_root(root)
        if not (gr / "gpt_tool" / "__main__.py").exists():
            raise RuntimeError(f"Thiếu tool GPT-TOOL: {gr}")
        if not (gr / ".venv" / "Scripts" / "python.exe").exists():
            raise RuntimeError(
                "GPT-TOOL chưa cài venv — chạy gpt-tool\\setup.bat một lần rồi Start lại"
            )

    def build_command(self, params: dict[str, Any], root: Path) -> list[str]:
        port = str(params.get("port") or "8083").strip() or "8083"
        return [str(self._py(root)), "-u", "-m", "gpt_tool", "web", "--port", port]

    def cwd(self, root: Path) -> Path:
        return self.gpt_root(root)

    def env_overrides(self, params: dict[str, Any]) -> dict[str, str]:
        return {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

    def stop_signal(self, root: Path) -> None:
        # GPT-TOOL dừng bằng cách tắt process — JobManager force-kill tree sau 8s
        pass

    def parse_results(self, root: Path, limit: int = 200) -> list[dict[str, Any]]:
        # Kết quả reg nằm trong web UI GPT-TOOL (:8083) — không có ledger chung
        return []

    def stats(self, root: Path) -> dict[str, Any]:
        return {
            "blurb": "Web app riêng — mở http://127.0.0.1:8083 khi job đang chạy",
        }
