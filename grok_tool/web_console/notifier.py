"""Fire-and-forget notifications: Telegram bot + generic webhook.

Cấu hình (config.json):
    "notify": {
        "telegram_bot_token": "123:abc",
        "telegram_chat_id": "123456",
        "webhook_url": "https://example.com/hook"
    }
Hoặc biến môi trường: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / NOTIFY_WEBHOOK_URL.
Chưa cấu hình gì → no-op. Mọi lỗi gửi đều bị nuốt (log warning) —
notification không bao giờ làm hỏng job.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT = 10


def _settings() -> dict[str, str]:
    token = chat = webhook = ""
    try:
        from grokreg.core.config import load_config

        notify = (load_config().get("notify") or {})
        if not isinstance(notify, dict):
            notify = {}
        token = str(notify.get("telegram_bot_token") or "").strip()
        chat = str(notify.get("telegram_chat_id") or "").strip()
        webhook = str(notify.get("webhook_url") or "").strip()
    except Exception:
        logger.debug("[notify] config load failed", exc_info=True)
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = chat or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    webhook = webhook or os.environ.get("NOTIFY_WEBHOOK_URL", "").strip()
    return {"tg_token": token, "tg_chat": chat, "webhook": webhook}


def configured() -> bool:
    s = _settings()
    return bool((s["tg_token"] and s["tg_chat"]) or s["webhook"])


def notify(event: str, message: str) -> bool:
    """Gửi notification (nếu đã cấu hình). Trả về True nếu có kênh sẽ gửi."""
    s = _settings()
    has_tg = bool(s["tg_token"] and s["tg_chat"])
    if not has_tg and not s["webhook"]:
        return False
    threading.Thread(
        target=_send, args=(s, event, message), daemon=True, name="notify"
    ).start()
    return True


def _send(s: dict[str, str], event: str, message: str) -> None:
    if s["tg_token"] and s["tg_chat"]:
        try:
            _send_telegram(s["tg_token"], s["tg_chat"], message)
        except Exception as e:
            logger.warning("[notify] telegram failed: %s", e)
    if s["webhook"]:
        try:
            _send_webhook(s["webhook"], event, message)
        except Exception as e:
            logger.warning("[notify] webhook failed: %s", e)


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        resp.read()


def _send_webhook(url: str, event: str, message: str) -> None:
    payload = json.dumps({"event": event, "message": message, "ts": time.time()}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        resp.read()
