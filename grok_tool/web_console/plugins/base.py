"""Plugin contract for registration tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class FieldOption:
    value: str
    label: str
    hint: str = ""


@dataclass
class ToolField:
    key: str
    label: str
    type: str = "text"  # text | number | select | checkbox | password | textarea
    default: Any = ""
    options: list[FieldOption] = field(default_factory=list)
    hint: str = ""
    min: Optional[int] = None
    max: Optional[int] = None


@dataclass
class ToolMeta:
    id: str
    name: str
    description: str
    icon: str = "◆"
    status: str = "ready"  # ready | beta | coming_soon
    fields: list[ToolField] = field(default_factory=list)
    color: str = "#229ed9"
    # Official publisher mark. Empty = auto /static/img/brands/{id}.svg|.png|.webp
    brand_icon: str = ""


def parse_pipe_accounts(path: Any, *, tool: str, classify, limit: int = 200) -> list[dict[str, Any]]:
    """Parse email|password|status|... ledger. Skip HTML/garbage leftover lines."""
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(p.read_text(encoding="utf-8", errors="replace").splitlines()):
        s = line.strip()
        if not s or s.startswith("#") or "|" not in s:
            continue
        parts = s.split("|")
        email = parts[0].strip() if parts else ""
        if "@" not in email or any(c.isspace() for c in email) or len(email) > 80:
            continue
        status = parts[2].strip() if len(parts) > 2 else ""
        kind = classify(status)
        rows.append(
            {
                "email": email,
                "password": parts[1].strip() if len(parts) > 1 else "",
                "status": status,
                "kind": kind,
                "ok": kind == "reg_ok",
                "tool": tool,
            }
        )
        if len(rows) >= limit:
            break
    return rows


class BaseToolPlugin:
    """Override for each registration tool."""

    meta: ToolMeta

    def proxy_config_path(self, root: Any) -> Optional[Path]:
        """File config.json nhận key 'proxy' từ pool chung của console.

        Trả None (mặc định) = tool này không bơm proxy tự động.
        """
        return None

    def apply_proxy(self, cmd: list[str], params: dict[str, Any], root: Any, proxy: str) -> list[str]:
        """Console gọi trước khi spawn khi pool proxy đang bật (hoặc tắt để dọn)."""
        from web_console import proxy_pool

        path = self.proxy_config_path(root)
        if path is not None:
            pool: Optional[list[str]] = None
            if str(proxy or "").strip():
                try:
                    pool = list(proxy_pool.get_state().get("proxies") or [])
                except Exception:  # noqa: BLE001 — không lấy được pool thì bơm 1 IP
                    pool = None
            proxy_pool.apply_proxy_to_config(Path(path), proxy, pool=pool)
        return cmd

    def build_command(self, params: dict[str, Any], root: Any) -> list[str]:
        raise NotImplementedError

    def cwd(self, root: Any) -> Any:
        return root

    def stop_signal(self, root: Any) -> None:
        """Write STOP / soft-stop for this tool."""
        pass

    def parse_results(self, root: Any, limit: int = 200) -> list[dict[str, Any]]:
        return []

    def stats(self, root: Any) -> dict[str, Any]:
        return {}
