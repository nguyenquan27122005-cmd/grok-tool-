"""KiotProxy — kéo pool proxy vào ``proxy_pool`` cho MỌI tool sibling.

Cấu hình chung 1 chỗ: ``grok_tool/data/kiotproxy.json``
  {"email": "...", "password": "...", "key": "Kd1fb...", "ttl_min": 30}
(tool nào cũng đọc được qua ensure_grok_on_path; file nằm trong data/**
nên không bao giờ lên git.)

``next_proxy`` gọi ``sync_if_needed`` tự động: pool cạn hoặc quá TTL → login
lấy Bearer → GET /api/management/kp/proxy/list → ghi đè ``proxy_pool`` trong
config (in-place, thread-safe). API lỗi thì giữ pool cũ, thử lại sau 5 phút.

API (JHipster-style, đã dò từ bundle app.kiotproxy.com):
  POST /api/authenticate {username, password} → id_token
  GET  /api/management/kp/proxy/list?page&size  (Bearer id_token)
Key mua (vd Kd1fb...) chỉ là định danh gói — list proxy theo account.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_BASE = "https://api.kiotproxy.com/api"
_LOCK = threading.Lock()
_LAST_TRY = 0.0
_RETRY_SEC = 300  # lỗi thì 5 phút mới thử lại, không nhồi API
_shared_dir: Path | None = None


def _shared() -> Path:
    global _shared_dir
    if _shared_dir is None:
        # grok_tool/data — module này nằm ở grok_tool/grokreg/core/
        _shared_dir = Path(__file__).resolve().parents[2] / "data"
        _shared_dir.mkdir(exist_ok=True)
    return _shared_dir


def _creds(config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict((config or {}).get("kiotproxy") or {})
    if not cfg.get("email"):
        f = _shared() / "kiotproxy.json"
        if f.exists():
            try:
                cfg = json.loads(f.read_text(encoding="utf-8")) or {}
            except Exception:
                cfg = {}
    return cfg


def _login(creds: dict[str, Any]) -> str:
    import requests

    r = requests.post(
        f"{_BASE}/authenticate",
        json={"username": creds.get("email"), "password": creds.get("password")},
        timeout=20,
    )
    body = r.json() or {}
    if not body.get("success"):
        raise RuntimeError(f"kiotproxy login: {str(body.get('message') or r.status_code)[:120]}")
    data = body.get("data") or {}
    return str(data.get("id_token") or data.get("token") or "")


def _row_url(row: dict[str, Any], key: str) -> str:
    host = next((str(row[k]) for k in ("host", "ip", "address", "server", "proxyHost") if row.get(k)), "")
    port = next((row[k] for k in ("port", "proxyPort") if row.get(k)), "")
    if not host or not port:
        raw = next((str(row[k]) for k in ("proxy", "url", "endpoint") if row.get(k)), "")
        return raw.strip()
    user = next((str(row[k]) for k in ("username", "user") if row.get(k)), "")
    pwd = next((str(row[k]) for k in ("password", "pass") if row.get(k)), "")
    if not user and key:
        user, pwd = key, key  # vài nhà cung cấp dùng key làm user/pass
    auth = f"{user}:{pwd}@" if (user and pwd) else ""
    scheme = "socks5" if int(port) in (1080, 1081) or str(row.get("type", "")).lower() == "socks5" else "http"
    return f"{scheme}://{auth}{host}:{port}"


def fetch_pool(config: dict[str, Any] | None = None) -> list[str]:
    """Login + kéo list proxy (theo key nếu đặt). Ném exception khi lỗi."""
    import requests

    creds = _creds(config)
    if not creds.get("email") or not creds.get("password"):
        raise RuntimeError("thiếu kiotproxy email/password")
    token = _login(creds)
    s = requests.Session()
    s.trust_env = False
    s.headers["Authorization"] = f"Bearer {token}"
    key = str(creds.get("key") or "")
    pool: list[str] = []
    for page in range(3):
        r = s.get(
            f"{_BASE}/management/kp/proxy/list",
            params={"page": page, "size": 100},
            timeout=20,
        )
        body = r.json() or {}
        rows = (body.get("data") or {})
        rows = rows.get("content") if isinstance(rows, dict) else rows
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            if key and str(row.get("key") or row.get("keyId") or "") not in (key, ""):
                continue
            u = _row_url(row, key)
            if u:
                pool.append(u)
        if len(rows) < 100:
            break
    if not pool:
        (Path(_shared()) / "kiotproxy_last.json").write_text(
            json.dumps(body, ensure_ascii=False, default=str)[:20000], encoding="utf-8"
        )
    return sorted(set(pool))


def sync_if_needed(config: dict[str, Any], *, force: bool = False) -> list[str]:
    """Đồng bộ pool KiotProxy vào ``config['proxy_pool']`` nếu đến hạn.

    Trả về pool hiện hành (KiotProxy hoặc pool tĩnh cũ). Không bao giờ ném —
    lỗi chỉ log và giữ pool cũ."""
    global _LAST_TRY
    creds = _creds(config)
    if not creds.get("email"):
        return [str(p).strip() for p in (config.get("proxy_pool") or []) if str(p).strip()]
    ttl = float(creds.get("ttl_min") or 30) * 60
    cache = _shared() / "kiotproxy_pool.json"
    with _LOCK:
        now = time.time()
        if not force:
            if cache.exists():
                try:
                    d = json.loads(cache.read_text(encoding="utf-8"))
                    if now - float(d.get("ts") or 0) < ttl and d.get("pool"):
                        config["proxy_pool"] = list(d["pool"])
                        return list(d["pool"])
                except Exception:
                    pass
            if now - _LAST_TRY < _RETRY_SEC:
                return [str(p).strip() for p in (config.get("proxy_pool") or []) if str(p).strip()]
        _LAST_TRY = now
        try:
            pool = fetch_pool(config)
            if pool:
                cache.write_text(
                    json.dumps({"ts": now, "pool": pool}, ensure_ascii=False), encoding="utf-8"
                )
                config["proxy_pool"] = pool
                return pool
        except Exception as e:
            print(f"[kiotproxy] sync: {str(e)[:140]}", flush=True)
        return [str(p).strip() for p in (config.get("proxy_pool") or []) if str(p).strip()]
