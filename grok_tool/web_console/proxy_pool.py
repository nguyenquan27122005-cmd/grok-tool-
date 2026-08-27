"""Pool proxy dùng chung cho MỌI tool trong console.

Nguyên lý: 9 tool CLI (grok + claude/heygen/capcut/zai/canva/netflix/manus/
notion) đều đọc proxy từ key ``"proxy"`` trong config.json của tool mình
(không ai nhận --proxy trên CLI), còn GPT-TOOL (:8083) nhận qua POST /api/config.
Nên console chỉ cần: lưu pool → mỗi lần Start pick 1 proxy → ghi vào đúng
config.json của tool sắp chạy → log ra proxy đã mask.

Store: data/proxy_pool.json — {"enabled", "mode", "proxies", "cursor"}.
mode "fixed" luôn dùng dòng đầu; "rotate" xoay vòng qua cursor (persist).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
STORE_PATH = ROOT / "data" / "proxy_pool.json"

GPTTOOL_URL = "http://127.0.0.1:8083"
GPT_CONFIG_TIMEOUT = 4.0
# DB của gpt-tool chứa settings (key web.auth_token) — console đọc trực tiếp
# (read-only) để gọi POST /api/config, khỏi phải cấu hình token tay.
GPT_DB = Path(r"D:\grok_tool\gpt-tool\runtime\data.db")


def _gpt_tool_token() -> str:
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{GPT_DB}?mode=ro", uri=True, timeout=3)
        try:
            row = con.execute(
                "SELECT value FROM settings WHERE key='web.auth_token'"
            ).fetchone()
        finally:
            con.close()
        # Giá trị lưu dạng JSON (vd '"abc…"') — phải bọc quote ra mới khớp
        # với token server so sánh, không thì header mang theo "…"
        # nguyên bản và bị chấm 401.
        raw = str(row[0]) if row and row[0] else ""
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, str):
                return decoded
        except ValueError:
            pass
        return raw
    except Exception:  # noqa: BLE001 — không đọc được thì coi như chưa có token
        return ""

_lock = threading.Lock()


def _load() -> dict[str, Any]:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "enabled": bool(data.get("enabled", False)),
                "mode": str(data.get("mode") or "rotate"),
                "proxies": [str(p) for p in (data.get("proxies") or [])],
                "cursor": int(data.get("cursor") or 0),
            }
    except Exception:  # noqa: BLE001 — file thiếu/hỏng = state mặc định
        pass
    return {"enabled": False, "mode": "rotate", "proxies": [], "cursor": 0}


def _save(state: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


_SCHEME_RE = re.compile(r"^(https?|socks4a?|socks5h?)://", re.IGNORECASE)
_DEFAULT_PORTS = {"http": 80, "https": 443, "socks4": 1080, "socks4a": 1080, "socks5": 1080, "socks5h": 1080}


def _normalize_one(raw: str) -> str:
    """1 dòng bất kỳ định dạng → URL chuẩn scheme://[user:pass@]host[:port].

    Nuốt được: host:port · user:pass@host:port · ip:port:user:pass ·
    http(s)://… · socks4/5(h/a)://… (có/không user:pass), tolerates ngoặc <> ,
    dấu phẩy/chấm phẩy cuối dòng.
    """
    p = raw.strip().strip(",;").strip().strip("<>").strip()
    if not p or p.startswith("#"):
        return ""
    if "://" not in p:
        parts = p.split(":")
        if len(parts) == 4 and parts[1].isdigit() and 0 < int(parts[1]) <= 65535:
            host, port, user, password = parts
            p = f"http://{user}:{password}@{host}:{port}"
        else:
            p = f"http://{p}"
    m = _SCHEME_RE.match(p)
    if not m:
        raise ValueError(f"scheme lạ: {raw.strip()!r}")
    scheme = m.group(1).lower()
    rest = p.split("://", 1)[1]
    if not rest:
        raise ValueError(f"thiếu host: {raw.strip()!r}")
    userinfo = ""
    hostport = rest
    if "@" in rest:
        userinfo, _, hostport = rest.rpartition("@")
        if not userinfo:
            raise ValueError(f"thiếu user:pass trước @: {raw.strip()!r}")
    # IPv6 dạng [::1]:port — tách port ngoài ngoặc vuông
    host, port = hostport, ""
    if hostport.startswith("["):
        close = hostport.find("]")
        if close == -1:
            raise ValueError(f"thiếu ] cho IPv6: {raw.strip()!r}")
        host, tail = hostport[1:close], hostport[close + 1:]
        if tail.startswith(":"):
            port = tail[1:]
        elif tail:
            raise ValueError(f"sai cú pháp sau ]: {raw.strip()!r}")
    elif ":" in hostport:
        host, _, port = hostport.rpartition(":")
    if not host:
        raise ValueError(f"thiếu host: {raw.strip()!r}")
    if port:
        if not port.isdigit() or not (0 < int(port) <= 65535):
            raise ValueError(f"port sai: {raw.strip()!r}")
    else:
        port = str(_DEFAULT_PORTS[scheme])
    out = f"{scheme}://" + (f"{userinfo}@" if userinfo else "") + host
    return f"{out}:{port}"


def normalize_lines(text: str) -> list[str]:
    """Mỗi dòng 1 proxy — nhận mọi dạng phổ biến. Bỏ trống/#. Lỗi cú pháp → ValueError."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        norm = _normalize_one(line)
        key = norm.lower()
        if key not in seen:
            seen.add(key)
            out.append(norm)
    return out


def mask(proxy: str) -> str:
    """Che user:pass khi log — scheme://***@host:port."""
    p = str(proxy or "")
    if "@" not in p:
        return p
    scheme, _, rest = p.partition("://")
    host = rest.rsplit("@", 1)[-1]
    return f"{scheme}://***@{host}" if scheme else f"***@{host}"


def get_state() -> dict[str, Any]:
    with _lock:
        return _load()


def validate_lines(text: str) -> list[str]:
    """Trả danh sách mô tả lỗi cho từng dòng sai cú pháp ([] = hợp lệ)."""
    errors: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            _normalize_one(line)
        except ValueError as exc:
            errors.append(f"“{line}” — {exc}")
    return errors


def save_state(
    *,
    enabled: Optional[bool] = None,
    mode: Optional[str] = None,
    proxies_text: Optional[str] = None,
) -> dict[str, Any]:
    with _lock:
        st = _load()
        if enabled is not None:
            st["enabled"] = bool(enabled)
        if mode in ("fixed", "rotate"):
            st["mode"] = mode
        if proxies_text is not None:
            st["proxies"] = normalize_lines(proxies_text)
            st["cursor"] = 0
        _save(st)
        return st


def pick() -> tuple[Optional[str], int]:
    """Chọn proxy cho 1 lần chạy. Trả ('', -1) nếu tắt / pool rỗng.
    mode rotate thì tăng cursor (persist) để lần sau sang proxy kế tiếp."""
    with _lock:
        st = _load()
        if not st.get("enabled"):
            return "", -1
        proxies = st.get("proxies") or []
        if not proxies:
            return "", -1
        mode = st.get("mode") or "rotate"
        if mode == "fixed":
            return proxies[0], 0
        idx = int(st.get("cursor") or 0) % len(proxies)
        st["cursor"] = idx + 1
        _save(st)
        return proxies[idx], idx


def apply_proxy_to_config(config_path: Path, proxy: str) -> None:
    """Ghi key 'proxy' vào config.json của tool, giữ nguyên mọi key khác."""
    path = Path(config_path)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:  # noqa: BLE001 — config hỏng thì ghi đè tối thiểu
            data = {}
    data["proxy"] = str(proxy)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sync_gpttool() -> str:
    """Đẩy pool vào GPT-TOOL :8083 (POST /api/config). Best-effort — service
    chưa chạy thì bỏ qua im lặng, không làm hỏng thao tác lưu của console."""
    st = get_state()
    body = {
        "use_proxy": bool(st.get("enabled")),
        "proxy": "\n".join(st.get("proxies") or []),
    }
    try:
        import urllib.request

        headers = {"Content-Type": "application/json"}
        token = _gpt_tool_token()
        if token:
            headers["X-API-Token"] = token
        req = urllib.request.Request(
            f"{GPTTOOL_URL}/api/config",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=GPT_CONFIG_TIMEOUT):
            return "đã đồng bộ sang GPT-TOOL :8083"
    except Exception as exc:  # noqa: BLE001
        reason = type(exc).__name__
        detail = str(exc)[:80]
        if "URLError" in reason or "Connection" in detail or "10061" in detail:
            return "GPT-TOOL :8083 không chạy — bỏ qua đồng bộ"
        return f"chưa đồng bộ được GPT-TOOL ({reason}: {detail})"
