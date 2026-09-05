"""Acquire inbox + wait OpenArt (Clerk) verification code (6 digits)."""

from __future__ import annotations

import re
import time
from typing import Any, Optional

import requests

from oareg.log import log
from oareg.paths import ROOT, ensure_grok_on_path
from oareg.stop import raise_if_stop

OPENART_HINTS = ("openart",)
# Clerk mail: subject "<code> is your verification code" hoặc code trong body
CODE_RE = re.compile(r"\b(\d{6})\b")
_SKIP_CODE = {"000000", "123456", "111111", "999999"}


def _blob_is_openart(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in OPENART_HINTS)


def extract_openart_code(text: str) -> str:
    codes = CODE_RE.findall(text or "")
    for c in codes:
        if c not in _SKIP_CODE:
            return c
    return ""


def acquire_email(config: dict[str, Any]):
    grok = ensure_grok_on_path()
    if not grok:
        raise RuntimeError("Khong thay folder grok_tool — can dat Openart canh grok_tool de dung mail")

    from grokreg.core.config import load_config as load_grok_cfg
    from grokreg.mail.mail_api import MailApiClient
    from grokreg.mail.providers import AzpopMailProvider, HotmailProvider, MailTmProvider
    from grokreg.mail.tmail_wibu import TmailWibuProvider
    from grokreg.reg.flow import acquire_email_session

    grok_cfg = {}
    try:
        grok_cfg = load_grok_cfg()
    except Exception:
        grok_cfg = {}

    merged = dict(grok_cfg)
    merged.update(config)
    want = str(config.get("email_provider") or "hotmail").strip().lower()
    if want in ("tmail", "3"):
        want = "tmail_wibu"
    if want in ("5", "custom", "custom_domain", "domain", "rieng"):
        want = "custom_domain"
    if want not in ("hotmail", "azpopmail", "tmail_wibu", "custom_domain"):
        want = "hotmail"
    merged["email_provider"] = want
    hl = str(config.get("hotmail_list") or "data/hotmails.txt")
    hp = ROOT / hl
    if not hp.exists() and (grok / "data" / "hotmails.txt").exists():
        merged["hotmail_list"] = str(grok / "data" / "hotmails.txt")
    else:
        merged["hotmail_list"] = hl

    mailtm = MailTmProvider()
    az_cfg = dict(grok_cfg.get("azpopmail") or {})
    az_cfg.update(config.get("azpopmail") or {})
    if not az_cfg.get("domains"):
        az_cfg["domains"] = list((grok_cfg.get("azpopmail") or {}).get("domains") or [])
    azpop = AzpopMailProvider(az_cfg)
    tmail = TmailWibuProvider(dict(merged.get("tmail_wibu") or grok_cfg.get("tmail_wibu") or {}))
    session, hotmail = acquire_email_session(merged, mailtm, azpop, tmail_wibu=tmail)

    addr = str(getattr(session, "address", "") or "")
    if want == "custom_domain":
        pass  # OTP đọc qua hotmail forward — session giữ nguyên
    elif want in ("azpopmail", "tmail_wibu"):
        # Clerk OpenArt chặn domain temp → chỉ dùng để test, Worker tự đổi mail
        log.warning("Provider %s có thể bị OpenArt chặn (temp domain) — nếu fail sẽ đổi Hotmail", want)
    return session, hotmail, MailApiClient(merged.get("mail_api") or {}), azpop, tmail, mailtm


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
        log.warning("Graph token HTTP %s %s", tok.status_code, tok.text[:160])
        return []
    access = (tok.json() or {}).get("access_token") or ""
    if not access:
        return []
    inbox = requests.get(
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
        "?$top=20&$orderby=receivedDateTime desc"
        "&$select=id,subject,from,body,bodyPreview,receivedDateTime",
        headers={"Authorization": f"Bearer {access}"},
        timeout=25,
    )
    if inbox.status_code != 200:
        log.warning("Graph inbox HTTP %s", inbox.status_code)
        return []
    return list((inbox.json() or {}).get("value") or [])


def _msg_text(m: dict[str, Any]) -> str:
    body = m.get("body")
    html = ""
    if isinstance(body, dict):
        html = str(body.get("content") or "")
    return " ".join(
        [
            str(m.get("subject") or ""),
            str(m.get("bodyPreview") or ""),
            html,
            str((m.get("from") or {}).get("emailAddress", {}).get("address") or ""),
        ]
    )


def _mail_ts(m: dict[str, Any]) -> str:
    return str(m.get("receivedDateTime") or "")


def wait_openart_code(
    session,
    config: dict[str, Any],
    *,
    mail_api=None,
    azpop=None,
    tmail=None,
    mailtm=None,
    timeout: int = 180,
    since_iso: str = "",
) -> str:
    """Return 6-digit code from an OpenArt (Clerk) verification mail."""
    deadline = time.time() + max(30, int(timeout))
    provider = str(getattr(session, "provider", "") or "")
    cid = str((config.get("mail_api") or {}).get("client_id") or "")
    log.info("Cho mail OpenArt (%s, timeout=%ss)…", provider, timeout)

    while time.time() < deadline:
        raise_if_stop()
        try:
            if provider in ("hotmail", "custom_domain"):
                for m in _graph_messages(session, cid):
                    blob = _msg_text(m)
                    if not _blob_is_openart(blob):
                        continue
                    if since_iso and _mail_ts(m) and _mail_ts(m) < since_iso:
                        continue
                    code = extract_openart_code(blob)
                    if code:
                        log.info("OpenArt code: %s", code)
                        return code
            elif provider == "azpopmail" and azpop:
                extra = session.extra or {}
                user = extra.get("username") or session.address.split("@")[0]
                domain = extra.get("domain") or session.address.split("@")[-1]
                msgs, _ = azpop._list_messages(user, domain)
                for m in msgs or []:
                    mid = str(m.get("id") or m.get("mail_id") or "")
                    body = ""
                    try:
                        body = azpop._message_body(user, domain, mid)
                    except Exception:
                        pass
                    blob = f"{m.get('subject', '')} {m.get('from', '')} {body}"
                    if not _blob_is_openart(blob):
                        continue
                    code = extract_openart_code(blob)
                    if code:
                        log.info("OpenArt code (azpop): %s", code)
                        return code
            elif provider == "tmail_wibu" and tmail:
                extra = dict(getattr(session, "extra", None) or {})
                try:
                    messages, html_blob = tmail._fetch_messages(session.address, extra)
                except Exception:
                    messages, html_blob = [], ""
                blob = html_blob or ""
                for msg in messages or []:
                    blob += " " + str(msg.get("subject") or "")
                if _blob_is_openart(blob):
                    code = extract_openart_code(blob)
                    if code:
                        log.info("OpenArt code (tmail): %s", code)
                        return code
            elif mailtm:
                otp = mailtm.wait_otp(session, timeout=8)
                if otp:
                    return otp
        except Exception as e:
            log.debug("mail poll: %s", e)
        time.sleep(3)
    return ""
