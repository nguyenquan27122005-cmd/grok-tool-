"""Xoay proxy theo TỪNG account cho mọi engine sibling (anti-flag chính).

Console bơm pool vào config.json của tool (key ``proxy_pool`` = list URL).
Engine gọi ``next_proxy(config)`` đầu mỗi account → config["proxy"] được thay
bằng 1 IP random trong pool (random — tránh pattern xoay đều đặn). Pool rỗng
→ trả nguyên config["proxy"] cũ. Thread-safe (batch nhiều luồng).

Nguồn KiotProxy: đặt creds trong ``grok_tool/data/kiotproxy.json`` — pool tự
đồng bộ theo TTL ở đây lẫn console (web_console.proxy_pool).
"""
from __future__ import annotations

import random
import threading
from typing import Any

_LOCK = threading.Lock()


def next_proxy(config: dict[str, Any]) -> str:
    pool = [str(p).strip() for p in (config.get("proxy_pool") or []) if str(p).strip()]
    if len(pool) < 2:
        try:
            from grokreg.core.kiotproxy import sync_if_needed

            pool = [p for p in sync_if_needed(config) if p]
        except Exception:  # noqa: BLE001 — không có creds/lỗi mạng thì dùng pool cũ
            pass
    if len(pool) >= 2:
        with _LOCK:
            return random.choice(pool)
    if len(pool) == 1:
        return pool[0]
    return str(config.get("proxy") or "")
