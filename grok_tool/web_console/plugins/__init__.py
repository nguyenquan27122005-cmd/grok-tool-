"""Tool plugin registry — add new tools here."""

from __future__ import annotations

from typing import Dict

from .base import BaseToolPlugin
from .grok import GrokToolPlugin
from .heygen import HeygenToolPlugin
from .capcut import CapcutToolPlugin
from .zai import ZaiToolPlugin
from .canva import CanvaToolPlugin
from .netflix import NetflixToolPlugin
from .manus import ManusToolPlugin
from .notion import NotionToolPlugin
from .claude import ClaudeToolPlugin
from .gpt import GptToolPlugin
from .dreamina import DreaminaToolPlugin
from .chatgpt import ChatgptToolPlugin
from .genspark import GensparkToolPlugin
from .openart import OpenartToolPlugin
from .scispace import ScispaceToolPlugin
from .xpilot import XpilotToolPlugin


_BRAND_COLORS = {
    "claude": "#D97757",
    "openai": "#10A37F",
}


def _coming_soon(tool_id: str, name: str, desc: str, icon: str = "◇") -> BaseToolPlugin:
    from .base import ToolMeta

    class _Soon(BaseToolPlugin):
        meta = ToolMeta(
            id=tool_id,
            name=name,
            description=desc,
            icon=icon,
            status="coming_soon",
            color=_BRAND_COLORS.get(tool_id, "#94a3b8"),
            fields=[],
        )

        def build_command(self, params, root):
            raise RuntimeError(f"Tool '{name}' chưa sẵn sàng — sắp ra mắt")

    return _Soon()


def all_plugins() -> Dict[str, BaseToolPlugin]:
    plugins: list[BaseToolPlugin] = [
        GrokToolPlugin(),
        HeygenToolPlugin(),
        CapcutToolPlugin(),
        ZaiToolPlugin(),
        CanvaToolPlugin(),
        NetflixToolPlugin(),
        ManusToolPlugin(),
        NotionToolPlugin(),
        ClaudeToolPlugin(),
        GptToolPlugin(),
        DreaminaToolPlugin(),
        ChatgptToolPlugin(),
        GensparkToolPlugin(),
        OpenartToolPlugin(),
        ScispaceToolPlugin(),
        XpilotToolPlugin(),
        # Icon: drop official mark at static/img/brands/{id}.svg — see brands/README.md
    ]
    return {p.meta.id: p for p in plugins}


def get_plugin(tool_id: str) -> BaseToolPlugin:
    reg = all_plugins()
    if tool_id not in reg:
        raise KeyError(f"Unknown tool: {tool_id}")
    return reg[tool_id]
