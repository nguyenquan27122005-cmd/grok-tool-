"""Inbox via grok_tool Azpop / Hotmail — not Guerrilla from the zip."""

from __future__ import annotations

import re
import time
from typing import Any

import requests

from capreg.log import log
from capreg.paths import ROOT, ensure_grok_on_path
from capreg.stop import raise_if_stop

HINTS = (
    "capcut",
    "bytedance",
    "tiktok",
    "lemon",
    "verification",
    "verify",
    "otp",
    "security code",
    "confirm",
)
CODE_RE = re.compile(r"\b(\d{6})\b")
CODE_LABELED = re.compile(
    r"(?:verification code|code is|otp|mã(?:\s+xác\s+nhận)?)\s*(?:is|:)?\s*(\d{4,8})",
    re.I,
)
# OTP chữ+số (Dreamina gửi dạng "verification code is JT4RYK") — chỉ nhận khi
# có nhãn rõ ràng và mã chứa cả chữ lẫn số để không nhặt từ thông thường.
ALNUM_LABELED = re.compile(
    r"(?:verification code|code is|your code)\s*(?:is|:)?\s*([A-Za-z0-9]{5,8})\b"
)
_SKIP = {"000000", "123456", "111111", "999999"}
GUERRILLA_API = "https://api.guerrillamail.com/ajax.php"


def _is_capcut_mail(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in HINTS) or "mail.capcut.com" in low


def extract_otp(text: str) -> str:
    raw = text or ""
    m = CODE_LABELED.search(raw)
    if m and m.group(1) not in _SKIP:
        return m.group(1)
    m = ALNUM_LABELED.search(raw)
    if m:
        c = m.group(1)
        if any(ch.isdigit() for ch in c) and any(ch.isalpha() for ch in c):
            return c
    found: list[str] = []
    for c in CODE_RE.findall(raw):
        if c in _SKIP:
            continue
        if c.startswith("20") and len(c) == 6:
            continue
        found.append(c)
    return found[0] if found else ""


class GuerrillaMail:
    """Temp inbox — CapCut gửi OTP vào đây, Azpop thì không."""

    def __init__(self) -> None:
        self._http = requests.Session()

    def create(self):
        from grokreg.mail.mail_api import EmailSession

        r = self._http.get(
            GUERRILLA_API, params={"f": "get_email_address"}, timeout=20
        )
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
        raise RuntimeError("Thiếu folder grok_tool cạnh capcut — cần mail Azpop/Hotmail")

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
    want = str(config.get("email_provider") or "guerrilla").strip().lower()
    if want in ("0", "auto_temp", "temp", "guerrilla", "guerrillamail"):
        want = "guerrilla"
    if want in ("3", "tmail", "tmail_wibu", "tmailwibu", "wibu"):
        want = "tmail_wibu"
    if want in ("5", "custom", "custom_domain", "domain", "rieng"):
        want = "custom_domain"
    if want not in ("hotmail", "azpopmail", "guerrilla", "tmail_wibu", "custom_domain"):
        want = "guerrilla"
    merged["email_provider"] = want
    hl = str(config.get("hotmail_list") or "data/hotmails.txt")
    hp = ROOT / hl
    if not hp.exists() and (grok / "data" / "hotmails.txt").exists():
        merged["hotmail_list"] = str(grok / "data" / "hotmails.txt")
    else:
        merged["hotmail_list"] = hl

    az_cfg = dict(grok_cfg.get("azpopmail") or {})
    az_cfg.update(config.get("azpopmail") or {})
    if not az_cfg.get("domains"):
        az_cfg["domains"] = list((grok_cfg.get("azpopmail") or {}).get("domains") or [])
    mailtm = MailTmProvider()
    azpop = AzpopMailProvider(az_cfg)
    tmail = TmailWibuProvider(merged.get("tmail_wibu") or grok_cfg.get("tmail_wibu") or {})
    guerrilla = GuerrillaMail()
    if want == "guerrilla":
        session = guerrilla.create()
        hotmail = None
    else:
        session, hotmail = acquire_email_session(merged, mailtm, azpop, tmail_wibu=tmail)
        addr = str(getattr(session, "address", "") or "").lower()
        # tmail_wibu là lựa chọn chủ đích — chỉ tự fallback guerrilla với azpop
        if want not in ("hotmail", "tmail_wibu") and (
            addr.endswith(".name.ng") or "wibucrypto" in addr
        ):
            log.warning("Bỏ mail spam %s — Guerrilla (CapCut không gửi Azpop/tmail)", addr)
            session = guerrilla.create()
            hotmail = None
    return session, hotmail, MailApiClient(merged.get("mail_api") or {}), azpop, tmail, mailtm, guerrilla


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
        "&$select=id,subject,from,toRecipients,ccRecipients,body,bodyPreview,receivedDateTime",
        headers={"Authorization": f"Bearer {access}"},
        timeout=25,
    )
    if inbox.status_code != 200:
        return []
    return list((inbox.json() or {}).get("value") or [])


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
        ]
    )


def wait_capcut_otp(
    session,
    config: dict[str, Any],
    *,
    mail_api=None,
    hotmail=None,
    azpop=None,
    tmail=None,
    mailtm=None,
    guerrilla=None,
    timeout: int = 120,
) -> str:
    deadline = time.time() + max(30, int(timeout))
    provider = str(getattr(session, "provider", "") or "")
    cid = str((config.get("mail_api") or {}).get("client_id") or "")
    log.info("Chờ OTP CapCut (%s, timeout=%ss)…", provider, timeout)

    while time.time() < deadline:
        raise_if_stop()
        try:
            blob = ""
            if provider == "guerrilla" and guerrilla:
                for m in guerrilla.list_messages(session) or []:
                    subj = str(m.get("mail_subject") or "")
                    frm = str(m.get("mail_from") or "")
                    if "guerrilla" in (subj + frm).lower() and "capcut" not in (subj + frm).lower():
                        continue
                    body = ""
                    mid = str(m.get("mail_id") or "")
                    if mid:
                        try:
                            body = guerrilla.fetch_body(session, mid)
                        except Exception:
                            pass
                    blob = f"{subj} {frm} {body}"
                    otp = extract_otp(blob)
                    if otp:
                        log.info("OTP Guerrilla: %s  (%s)", otp, subj[:80])
                        return otp
            elif provider in ("hotmail", "custom_domain"):
                target = (
                    str(getattr(session, "address", "") or "").lower()
                    if provider == "custom_domain"
                    else ""
                )
                for m in _graph_messages(session, cid):
                    blob = _msg_text(m)
                    if not _is_capcut_mail(blob):
                        continue
                    if target and not _msg_to(m, target):
                        continue
                    otp = extract_otp(blob)
                    if otp:
                        log.info("OTP %s: %s", provider, otp)
                        return otp
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
                    if not _is_capcut_mail(blob) and not extract_otp(blob):
                        continue
                    otp = extract_otp(blob)
                    if otp:
                        log.info("OTP Azpop: %s", otp)
                        return otp
            elif provider == "tmail_wibu" and tmail:
                # Đúng pattern canva: rehandshake qua _fetch_messages(address) —
                # _scrape_mailbox_page chỉ thấy hộp của session provider, không
                # phải hộp của địa chỉ đích.
                extra = dict(getattr(session, "extra", None) or {})
                html_blob = ""
                messages: list = []
                try:
                    messages, html_blob = tmail._fetch_messages(session.address, extra)
                except Exception as e:
                    log.debug("tmail fetch %s: %s", session.address, e)
                for m in messages or []:
                    try:
                        blob = tmail._msg_blob(m)
                    except Exception:
                        blob = re.sub(r"<[^>]+>", " ", str(m))
                    if not _is_capcut_mail(blob):
                        continue
                    otp = extract_otp(blob)
                    if otp:
                        log.info("OTP tmail: %s  (%s)", otp, str(m.get("subject") or "")[:60])
                        return otp
                if html_blob and _is_capcut_mail(html_blob):
                    otp = extract_otp(html_blob)
                    if otp:
                        log.info("OTP tmail (html): %s", otp)
                        return otp
            elif mailtm:
                otp = mailtm.wait_otp(session, timeout=8)
                if otp and extract_otp(str(otp)):
                    return extract_otp(str(otp))
        except Exception as e:
            log.debug("mail poll: %s", e)
        time.sleep(3)
    return ""
