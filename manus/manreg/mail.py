"""Acquire inbox + wait Manus verification (code or magic link)."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import unquote

import requests

from manreg.log import log
from manreg.paths import ROOT, ensure_grok_on_path
from manreg.stop import raise_if_stop

HINTS = (
    "manus",
    "butterfly",
    "verification",
    "verify",
    "confirm",
    "one-time",
    "otp",
    "security code",
    "sign up",
    "signup",
    "magic link",
    "sign-in code",
)
CODE_RE = re.compile(r"\b(\d{4,8})\b")
CODE_LABELED = re.compile(
    r"(?:verification code|code is|otp|mã(?:\s+xác\s+nhận)?)\s*(?:is|:)?\s*(\d{4,8})",
    re.I,
)
# Mail Manus viết "…verification code to confirm your email address: 382116" —
# từ khóa và mã cách nhau cả câu nên cần mẫu lỏng cho phép xen chữ ở giữa.
CODE_LOOSE = re.compile(
    r"(?:verification code|security code|one-time code|otp|mã xác nhận)[^0-9]{0,80}?(\d{4,8})\b",
    re.I,
)
LINK_RE = re.compile(
    r"https?://(?:www\.)?(?:manus\.im|manus\.ai)[^\s\"'<>]*(?:verify|confirm|magic|token|login|auth|invite)[^\s\"'<>]*",
    re.I,
)
ANY_LINK = re.compile(r"https?://(?:www\.)?(?:manus\.im|manus\.ai)/[^\s\"'<>]{8,}", re.I)
_SKIP = {"000000", "123456", "111111", "999999"}
GUERRILLA_API = "https://api.guerrillamail.com/ajax.php"


def _blob_is_target(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in HINTS)


def _visible_text(text: str) -> str:
    """Bỏ style/script/tag + giải entity — chỉ giữ phần người đọc thấy.

    Khớp mã OTP trên HTML thô sẽ ăn nhầm số trong CSS của mail (1999,
    262626, 595959… là z-index/màu) — đã gặp thật, OTP sai → verify fail.
    """
    t = re.sub(r"<(style|script)[\s\S]*?</\1>", " ", text or "", flags=re.I)
    try:
        import html as _html

        t = _html.unescape(t)
    except Exception:  # noqa: BLE001
        pass
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def extract_proof(text: str) -> dict[str, str]:
    raw = unquote(text or "")
    out: dict[str, str] = {}
    m = LINK_RE.search(raw) or ANY_LINK.search(raw)
    if m:
        link = m.group(0).rstrip(").,]>\"'")
        if not any(x in link.lower() for x in (".css", ".js", ".png", ".svg", "/asset/", ".woff")):
            out["link"] = link
    visible = _visible_text(raw)
    m = CODE_LABELED.search(visible) or CODE_LOOSE.search(visible)
    if m and m.group(1) not in _SKIP:
        out["code"] = m.group(1)
        return out
    for c in CODE_RE.findall(visible):
        if c in _SKIP:
            continue
        if c.startswith("20") and len(c) == 4:
            continue
        if len(c) < 4:
            continue
        out["code"] = c
        break
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
        raise RuntimeError("Thiếu folder grok_tool cạnh manus — cần mail Azpop/Hotmail")

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
    want = str(config.get("email_provider") or "azpopmail").strip().lower()
    if want in ("0", "auto_temp", "temp"):
        want = "azpopmail"
    if want in ("4", "guerrilla", "guerrillamail"):
        want = "guerrilla"
    if want in ("3", "tmail", "tmail_wibu"):
        want = "tmail_wibu"
    if want not in ("hotmail", "azpopmail", "guerrilla", "tmail_wibu"):
        want = "azpopmail"
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
        if want == "azpopmail" and (addr.endswith(".name.ng") or "wibucrypto" in addr):
            log.warning("Bỏ mail spam %s — tạo azpop", addr)
            session = azpop.create()
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
        log.warning("Graph token HTTP %s %s", tok.status_code, tok.text[:120])
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
) -> dict[str, str]:
    deadline = time.time() + max(30, int(timeout))
    provider = str(getattr(session, "provider", "") or "")
    cid = str((config.get("mail_api") or {}).get("client_id") or "")
    log.info("Chờ mail Manus (%s, timeout=%ss)…", provider, timeout)

    while time.time() < deadline:
        raise_if_stop()
        try:
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
                    if not _blob_is_target(blob):
                        continue
                    proof = extract_proof(blob)
                    if proof:
                        log.info("Manus mail Guerrilla: %s", proof)
                        return proof
            elif provider == "hotmail":
                for m in _graph_messages(session, cid):
                    blob = _msg_text(m)
                    if not _blob_is_target(blob):
                        continue
                    proof = extract_proof(blob)
                    if proof:
                        log.info("Manus mail Hotmail: %s", proof)
                        return proof
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
                    if not _blob_is_target(blob) and not extract_proof(blob):
                        continue
                    proof = extract_proof(blob)
                    if proof:
                        log.info("Manus mail Azpop: %s", proof)
                        return proof
            elif provider == "tmail_wibu" and tmail:
                extra = dict(getattr(session, "extra", None) or {})
                page_html = ""
                try:
                    page_otp, page_html, _ = tmail._scrape_mailbox_page(extra)
                    blob = page_html or ""
                    if page_otp:
                        blob = f"{blob} {page_otp}"
                    proof = extract_proof(blob)
                    if proof:
                        log.info("Manus mail tmail page: %s", proof)
                        return proof
                except Exception as e:
                    log.debug("tmail scrape: %s", e)
                try:
                    messages, html_blob = tmail._fetch_messages(session.address, extra)
                    blob = html_blob or ""
                    for msg in messages or []:
                        blob += " " + tmail._msg_blob(msg)
                        mid = str(msg.get("id") or msg.get("uid") or "")
                        if mid and hasattr(tmail, "_open_message"):
                            try:
                                blob += " " + (tmail._open_message(session.address, extra, mid) or "")
                            except Exception:
                                pass
                    proof = extract_proof(blob)
                    if proof:
                        log.info("Manus mail tmail: %s", proof)
                        return proof
                except Exception as e:
                    log.debug("tmail fetch: %s", e)
            elif mailtm:
                otp = mailtm.wait_otp(session, timeout=8)
                if otp:
                    return {"code": str(otp)}
        except Exception as e:
            log.debug("mail poll: %s", e)
        time.sleep(3)
    return {}
