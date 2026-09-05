"""KiotProxy — kéo proxy theo KEY vào ``proxy_pool`` cho MỌI tool sibling.

Cấu hình chung 1 chỗ: ``grok_tool/data/kiotproxy.json``
  {"key": "Kd1fb...", "region": "random", "ttl_min": 18}
(key là đủ — API v1 của KiotProxy không cần login account; region
bac/trung/nam/random, ttl_min =每隔 bao lâu thì kéo IP mới.)

``next_proxy`` gọi ``sync_if_needed`` tự động: proxy hết hạn/không có → gọi
``/api/v1/proxies/current`` (rồi ``/proxies/new`` nếu chưa gán) → ghi đè
``proxy_pool`` trong config (in-place, thread-safe). Lỗi giữ pool cũ, thử lại
sau 5 phút. Console (web_console.proxy_pool) cũng tự sync cùng nguồn.

API (tài liệu chính thức app.kiotproxy.com/access/api-documentation):
  GET /api/v1/proxies/current?key=   → proxy đang gán (404-ish nếu chưa có)
  GET /api/v1/proxies/new?key=&region= → đổi/lấy mới (giới hạn bởi ttc)
  data.http = "ip:port" (HTTP), ttl 1200s — 1 key giữ 1 IP tại một thời điểm.
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
    if not cfg.get("key"):
        f = _shared() / "kiotproxy.json"
        if f.exists():
            try:
                cfg = json.loads(f.read_text(encoding="utf-8")) or {}
            except Exception:
                cfg = {}
    return cfg


def fetch_pool(config: dict[str, Any] | None = None) -> tuple[list[str], float]:
    """Lấy proxy hiện tại của key (chưa gán thì đổi mới theo region).

    Trả về ``(pool, expires_at_epoch_sec)`` — pool có 0 hoặc 1 proxy (1 key = 1 IP).
    Ném exception khi lỗi API."""
    import requests

    creds = _creds(config)
    key = str(creds.get("key") or "").strip()
    if not key:
        raise RuntimeError("thiếu kiotproxy key")
    s = requests.Session()
    s.trust_env = False
    body: dict[str, Any] = {}
    for attempt in (2, 1):
        r = s.get(
            f"{_BASE}/v1/proxies/current" if attempt == 2 else f"{_BASE}/v1/proxies/new",
            params={"key": key, **({"region": str(creds.get("region") or "random")} if attempt == 1 else {})},
            timeout=20,
        )
        body = r.json() or {}
        if body.get("success") and (body.get("data") or {}).get("http"):
            break
        if str(body.get("error") or "") != "PROXY_NOT_FOUND_BY_KEY":
            break  # lỗi khác (key sai, đang hạn chế ttc…) — không thử /new nữa
    if not (body.get("success") and (body.get("data") or {}).get("http")):
        raise RuntimeError(str(body.get("message") or body.get("error") or r.status_code)[:140])
    data = body["data"]
    expires = float(data.get("expirationAt") or 0) / 1000.0
    return [f"http://{data['http']}"], expires


def sync_if_needed(config: dict[str, Any], *, force: bool = False) -> list[str]:
    """Đồng bộ pool KiotProxy vào ``config['proxy_pool']`` nếu hết hạn/không có.

    Không bao giờ ném — lỗi chỉ log và giữ pool cũ."""
    global _LAST_TRY
    creds = _creds(config)
    if not creds.get("key"):
        return [str(p).strip() for p in (config.get("proxy_pool") or []) if str(p).strip()]
    ttl_min = float(creds.get("ttl_min") or 18)
    cache = _shared() / "kiotproxy_pool.json"
    with _LOCK:
        now = time.time()
        if not force:
            if cache.exists():
                try:
                    d = json.loads(cache.read_text(encoding="utf-8"))
                    fresh = now < float(d.get("expires_at") or 0) - 60
                    young = now - float(d.get("ts") or 0) < ttl_min * 60
                    if (fresh or young) and d.get("pool"):
                        config["proxy_pool"] = list(d["pool"])
                        return list(d["pool"])
                except Exception:
                    pass
            if now - _LAST_TRY < _RETRY_SEC:
                return [str(p).strip() for p in (config.get("proxy_pool") or []) if str(p).strip()]
        _LAST_TRY = now
        try:
            pool, expires = fetch_pool(config)
            if pool:
                cache.write_text(
                    json.dumps({"ts": now, "pool": pool, "expires_at": expires}, ensure_ascii=False),
                    encoding="utf-8",
                )
                config["proxy_pool"] = pool
                print(f"[kiotproxy] pool: {pool[0].split('@')[-1]}", flush=True)
                return pool
        except Exception as e:
            print(f"[kiotproxy] sync: {str(e)[:140]}", flush=True)
        return [str(p).strip() for p in (config.get("proxy_pool") or []) if str(p).strip()]
