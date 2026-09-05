"""Inbox Hotmail (Graph) cho reg Z.ai — z.ai chặn domain temp nên chỉ còn hotmail."""

from __future__ import annotations

import re
import time
from typing import Any

import requests

from zaireg.log import log
from zaireg.paths import ROOT, ensure_grok_on_path
from zaireg.stop import raise_if_stop

HINTS = (
    "z.ai",
    "zcode",
    "chatglm",
    "zhipu",
    "verification",
    "verify",
    "confirm",
    "otp",
    "sign up",
    "signup",
)
CODE_RE = re.compile(r"\b(\d{6})\b")
CODE_LABELED = re.compile(
    r"(?:verification code|code is|otp|mã(?:\s+xác\s+nhận)?)\s*(?:is|:)?\s*(\d{4,8})",
    re.I,
)
TOKEN_RE = re.compile(
    r"(?:https?://(?:chat\.)?z\.ai[^\s\"'<>]*[?&](?:token|code|verify)=)([A-Za-z0-9_\-.]{8,})",
    re.I,
)
TOKEN_BARE = re.compile(r"(?:token|verify)[=: ]+([A-Za-z0-9_\-.]{16,})", re.I)
_SKIP = {"000000", "123456", "111111", "999999"}


def extract_verify(text: str) -> str:
    raw = text or ""
    m = TOKEN_RE.search(raw)
    if m:
        return m.group(1)
    m = TOKEN_BARE.search(raw)
    if m:
        return m.group(1)
    m = CODE_LABELED.search(raw)
    if m and m.group(1) not in _SKIP:
        return m.group(1)
    for c in CODE_RE.findall(raw):
        if c in _SKIP:
            continue
        if c.startswith("20") and len(c) == 6:
            continue
        return c
    return ""


def acquire_email(config: dict[str, Any]):
    """Cấp mailbox Hotmail từ pool (z.ai chặn domain temp — EMAIL_DOMAIN_BLOCKED).

    Trả về ``(session, hotmail, mail_api)`` — session đã là alias ``+N`` kế tiếp."""
    grok = ensure_grok_on_path()
    if not grok:
        raise RuntimeError("Thiếu folder grok_tool cạnh zai — cần mail")

    from grokreg.core.config import load_config as load_grok_cfg
    from grokreg.mail.mail_api import MailApiClient
    from grokreg.reg.flow import acquire_email_session

    grok_cfg: dict[str, Any] = {}
    try:
        grok_cfg = load_grok_cfg()
    except Exception:
        grok_cfg = {}

    merged = dict(grok_cfg)
    merged.update(config)
    merged["email_provider"] = "hotmail"
    hl = str(config.get("hotmail_list") or "data/hotmails.txt")
    hp = ROOT / hl
    # grokreg resolve hotmail_list theo ROOT của NÓ (grok_tool) — phải truyền
    # đường dẫn TUYỆT ĐỐI thì pool của zai mới không bị shadow bởi file rỗng
    # data/hotmails.txt của grok_tool.
    if hp.exists():
        merged["hotmail_list"] = str(hp)
    elif (grok / "data" / "hotmails.txt").exists():
        merged["hotmail_list"] = str(grok / "data" / "hotmails.txt")
    else:
        merged["hotmail_list"] = hl

    # mode bị ép "hotmail" — 2 tham số provider temp của grokreg không chạm tới
    session, hotmail = acquire_email_session(merged, None, None)
    return session, hotmail, MailApiClient(merged.get("mail_api") or {})


def _graph_messages(session, client_id: str) -> list[dict[str, Any]]:
    rt = getattr(session, "refresh_token", "") or ""
    cid = getattr(session, "client_id", "") or client_id
    if not rt:
        return []
    tok = requests.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "client_id": cid,
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "scope": "https://graph.microsoft.com/Mail.Read offline_access",
        },
        timeout=25,
    )
    if tok.status_code != 200:
        return []
    access = (tok.json() or {}).get("access_token") or ""
    if not access:
        return []
    inbox = requests.get(
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
        "?$top=20&$orderby=receivedDateTime desc"
        "&$select=id,subject,from,body,bodyPreview,receivedDateTime,toRecipients",
        headers={"Authorization": f"Bearer {access}"},
        timeout=25,
    )
    if inbox.status_code != 200:
        return []
    return list((inbox.json() or {}).get("value") or [])


def _msg_text(m: dict[str, Any]) -> str:
    body = m.get("body")
    html = ""
    if isinstance(body, dict):
        html = str(body.get("content") or "")
    return " ".join([str(m.get("subject") or ""), str(m.get("bodyPreview") or ""), html])


def wait_zai_verify(
    session,
    config: dict[str, Any],
    *,
    timeout: int = 180,
) -> str:
    deadline = time.time() + max(30, int(timeout))
    cid = str((config.get("mail_api") or {}).get("client_id") or "")
    want = str(getattr(session, "address", "") or "").lower()
    log.info("Chờ mail verify Z.ai Hotmail (%s, timeout=%ss)…", want, timeout)

    while time.time() < deadline:
        raise_if_stop()
        try:
            for m in _graph_messages(session, cid):
                # mailbox dùng chung cho nhiều alias (+1, +2…) — chỉ đọc
                # mail gửi ĐÚNG địa chỉ của session này, tránh lấy nhầm
                # OTP của alias khác khi prefetch chạy song song
                rcps = [
                    str(r.get("emailAddress", {}).get("address", "")).lower()
                    for r in (m.get("toRecipients") or [])
                ]
                if want and rcps and want not in rcps:
                    continue
                blob = _msg_text(m)
                if not any(h in blob.lower() for h in HINTS):
                    continue
                tok = extract_verify(blob)
                if tok:
                    log.info("Verify Hotmail: %s", tok[:24])
                    return tok
        except Exception as e:
            log.debug("mail poll: %s", e)
        time.sleep(3)
    return ""
