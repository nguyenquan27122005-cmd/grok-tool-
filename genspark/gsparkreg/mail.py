"""Inbox via grok_tool Hotmail / tmail / Azpop / Guerrilla."""

from __future__ import annotations

import re
import time
from typing import Any

import requests

from gsparkreg.log import log
from gsparkreg.paths import ROOT, ensure_grok_on_path
from gsparkreg.stop import raise_if_stop

HINTS = (
    "genspark",
    "mainfunc",
    "verification",
    "verify",
    "confirm",
    "otp",
    "sign up",
    "signup",
    "login code",
    "security code",
    "one-time",
    "verification code",
)
CODE_RE = re.compile(r"\b(\d{6})\b")
CODE_LABELED = re.compile(
    r"(?:verification code|login code|security code|code is|otp|mã(?:\s+xác\s+nhận)?)\s*(?:is|:)?\s*(\d{4,8})",
    re.I,
)
LINK_RE = re.compile(
    r"https?://(?:www\.)?(?:genspark\.ai|login\.genspark\.ai)/[^\s\"'<>]+",
    re.I,
)
_SKIP_LINK = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|css|js)(?:\?|$)", re.I)
_SKIP = {"000000", "123456", "111111", "999999"}
GUERRILLA_API = "https://api.guerrillamail.com/ajax.php"


def extract_verify(text: str) -> dict[str, str]:
    raw = text or ""
    out = {"code": "", "link": ""}
    for m in LINK_RE.finditer(raw):
        href = m.group(0).rstrip(").,]")
        if "/images/" in href or _SKIP_LINK.search(href):
            continue
        if "magic-link" in href or "/login" in href or "click?" in href:
            out["link"] = href
            break
    if not out["link"]:
        for m in LINK_RE.finditer(raw):
            href = m.group(0).rstrip(").,]")
            if "/images/" not in href and not _SKIP_LINK.search(href):
                out["link"] = href
                break
    m = CODE_LABELED.search(raw)
    if m and m.group(1) not in _SKIP:
        out["code"] = m.group(1)
        return out
    for c in CODE_RE.findall(raw):
        if c in _SKIP:
            continue
        if c.startswith("20") and len(c) == 6:
            continue
        out["code"] = c
        return out
    return out


class GuerrillaMail:
    def __init__(self) -> None:
        self._http = requests.Session()

    def create(self):
        from grokreg.mail.mail_api import EmailSession

        r = self._http.get(GUERRILLA_API, params={"f": "get_email_address"}, timeout=20)
        r.raise_for_status()
        d = r.json() or {}
        email = str(d.get("email_addr") or "").strip()
        sid = str(d.get("sid_token") or "").strip()
        if not email or not sid:
            raise RuntimeError(f"Guerrilla create fail: {d}")
        log.info("Guerrilla ready: %s", email)
        return EmailSession(
            address=email,
            password="",
            provider="guerrilla",
            token=sid,
            extra={"sid_token": sid, "email_addr": email},
        )

    def list_messages(self, session) -> list[dict[str, Any]]:
        sid = (session.extra or {}).get("sid_token") or session.token
        r = self._http.get(
            GUERRILLA_API,
            params={"f": "check_email", "seq": "0", "sid_token": sid},
            timeout=20,
        )
        r.raise_for_status()
        return list((r.json() or {}).get("list") or [])

    def fetch_body(self, session, mail_id: str) -> str:
        sid = (session.extra or {}).get("sid_token") or session.token
        r = self._http.get(
            GUERRILLA_API,
            params={"f": "fetch_email", "email_id": str(mail_id), "sid_token": sid},
            timeout=20,
        )
        r.raise_for_status()
        return str((r.json() or {}).get("mail_body") or "")


def acquire_email(config: dict[str, Any]):
    grok = ensure_grok_on_path()
    if not grok:
        raise RuntimeError("Thiếu folder grok_tool cạnh genspark — cần mail")

    from grokreg.core.config import load_config as load_grok_cfg
    from grokreg.mail.mail_api import MailApiClient
    from grokreg.mail.providers import AzpopMailProvider, MailTmProvider
    from grokreg.mail.tmail_wibu import TmailWibuProvider
    from grokreg.reg.flow import acquire_email_session

    grok_cfg: dict[str, Any] = {}
    try:
        grok_cfg = load_grok_cfg()
    except Exception:
        grok_cfg = {}

    merged = dict(grok_cfg)
    merged.update(config)
    want = str(config.get("email_provider") or "hotmail").strip().lower()
    alias = {
        "0": "auto_temp",
        "temp": "auto_temp",
        "smart": "auto_temp",
        "1": "hotmail",
        "2": "azpopmail",
        "azpop": "azpopmail",
        "3": "tmail_wibu",
        "tmail": "tmail_wibu",
        "wibu": "tmail_wibu",
        "4": "guerrilla",
        "guerrillamail": "guerrilla",
        "5": "custom_domain",
        "custom": "custom_domain",
        "domain": "custom_domain",
        "rieng": "custom_domain",
    }
    want = alias.get(want, want)
    if want not in ("hotmail", "azpopmail", "tmail_wibu", "guerrilla", "auto_temp", "custom_domain"):
        want = "hotmail"
    merged["email_provider"] = want
    hl = str(config.get("hotmail_list") or "../grok_tool/data/hotmails.txt")
    hp = ROOT / hl
    if not hp.exists() and (grok / "data" / "hotmails.txt").exists():
        merged["hotmail_list"] = str(grok / "data" / "hotmails.txt")
    else:
        merged["hotmail_list"] = hl

    az_cfg = dict(grok_cfg.get("azpopmail") or {})
    az_cfg.update(config.get("azpopmail") or {})
    mailtm = MailTmProvider()
    azpop = AzpopMailProvider(az_cfg)
    tmail = TmailWibuProvider(merged.get("tmail_wibu") or grok_cfg.get("tmail_wibu") or {})
    guerrilla = GuerrillaMail()
    if want == "guerrilla":
        session = guerrilla.create()
        hotmail = None
    else:
        session, hotmail = acquire_email_session(merged, mailtm, azpop, tmail_wibu=tmail)
    return session, hotmail, MailApiClient(merged.get("mail_api") or {}), azpop, tmail, mailtm, guerrilla


# OTP hay rơi vào Junk (đã bắt được mã Canva/Claude nằm ở Junk trong khi tool chỉ quét Inbox)
GRAPH_FOLDERS = ("inbox", "junkemail")


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
    msgs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for folder in GRAPH_FOLDERS:
        try:
            r = requests.get(
                f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages"
                "?$top=20&$orderby=receivedDateTime desc"
                "&$select=id,subject,from,body,bodyPreview,receivedDateTime,toRecipients,ccRecipients",
                headers={"Authorization": f"Bearer {access}"},
                timeout=25,
            )
        except Exception:
            continue
        if r.status_code != 200:
            continue
        for m in (r.json() or {}).get("value") or []:
            mid = str(m.get("id") or "")
            if mid and mid in seen:
                continue
            if mid:
                seen.add(mid)
            msgs.append(m)
    msgs.sort(key=lambda m: str(m.get("receivedDateTime") or ""), reverse=True)
    return msgs


def _msg_text(m: dict[str, Any]) -> str:
    body = m.get("body")
    html = ""
    if isinstance(body, dict):
        html = str(body.get("content") or "")
    return " ".join([str(m.get("subject") or ""), str(m.get("bodyPreview") or ""), html])


def _msg_to(m: dict[str, Any], addr: str) -> bool:
    """Mail gửi tới đúng địa chỉ (custom domain forward — 1 hộp đọc chung)."""
    want = (addr or "").strip().lower()
    if not want:
        return True
    for key in ("toRecipients", "ccRecipients"):
        for item in m.get(key) or []:
            if isinstance(item, dict):
                a = str((item.get("emailAddress") or {}).get("address") or "").lower()
                if a == want:
                    return True
    blob = f"{str(m.get('subject') or '')} {str(m.get('bodyPreview') or '')}".lower()
    return want in blob


def wait_mail(
    session,
    config: dict[str, Any],
    *,
    mail_api=None,
    hotmail=None,
    azpop=None,
    tmail=None,
    mailtm=None,
    guerrilla=None,
    timeout: int = 180,
    after_ts: float | None = None,
) -> dict[str, str]:
    deadline = time.time() + max(30, int(timeout))
    provider = str(getattr(session, "provider", "") or "")
    cid = str((config.get("mail_api") or {}).get("client_id") or "")
    log.info("Chờ mail Genspark OTP (%s, timeout=%ss)…", provider, timeout)

    def _fresh_graph(m: dict[str, Any]) -> bool:
        if not after_ts:
            return True
        rec = str(m.get("receivedDateTime") or "")
        if not rec:
            return False
        try:
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(rec.replace("Z", "+00:00"))
            ok = dt.timestamp() >= (after_ts - 8)
            if not ok:
                log.debug("skip old mail %s", rec)
            return ok
        except Exception:
            return False

    while time.time() < deadline:
        raise_if_stop()
        try:
            blob = ""
            if provider == "guerrilla" and guerrilla:
                for m in guerrilla.list_messages(session) or []:
                    subj = str(m.get("mail_subject") or "")
                    frm = str(m.get("mail_from") or "")
                    body = ""
                    mid = str(m.get("mail_id") or "")
                    if mid:
                        try:
                            body = guerrilla.fetch_body(session, mid)
                        except Exception:
                            pass
                    blob = f"{subj} {frm} {body}"
                    tok = extract_verify(blob)
                    if tok.get("code") or tok.get("link"):
                        log.info("OTP Guerrilla: %s (%s)", tok.get("code") or tok.get("link")[:40], subj[:80])
                        return tok
            elif provider in ("hotmail", "custom_domain"):
                target = (
                    str(getattr(session, "address", "") or "").lower()
                    if provider == "custom_domain"
                    else ""
                )
                for m in _graph_messages(session, cid):
                    rec = str(m.get("receivedDateTime") or "")
                    subj = str(m.get("subject") or "")
                    if after_ts:
                        log.debug("graph %s rec=%s", subj[:40], rec)
                    if not _fresh_graph(m):
                        continue
                    blob = _msg_text(m)
                    if not any(h in blob.lower() for h in HINTS):
                        continue
                    if target and not _msg_to(m, target):
                        continue
                    tok = extract_verify(blob)
                    if tok.get("code") or tok.get("link"):
                        log.info(
                            "OTP %s: %s rec=%s subj=%s",
                            provider,
                            tok.get("code") or tok.get("link")[:48],
                            rec,
                            subj[:60],
                        )
                        return tok
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
                    blob = f"{m.get('subject','')} {m.get('from','')} {body}"
                    tok = extract_verify(blob)
                    if tok.get("code") or tok.get("link"):
                        log.info("OTP Azpop: %s", tok.get("code") or "link")
                        return tok
            elif provider in ("tmail_wibu", "tmail") and tmail:
                try:
                    otp = tmail.wait_otp(session, timeout=8)
                except Exception:
                    otp = ""
                tok = extract_verify(str(otp or ""))
                if tok.get("code") or tok.get("link"):
                    log.info("OTP tmail: %s", tok.get("code") or "link")
                    return tok
            elif mailtm:
                otp = mailtm.wait_otp(session, timeout=8)
                if otp:
                    tok = extract_verify(str(otp))
                    if tok.get("code") or tok.get("link"):
                        return tok
        except Exception as e:
            log.debug("mail poll: %s", e)
        time.sleep(3)
    return {"code": "", "link": ""}
