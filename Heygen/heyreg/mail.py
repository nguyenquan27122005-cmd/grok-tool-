"""Acquire inbox + wait HeyGen verification (code or link)."""

from __future__ import annotations

import re
import time
from typing import Any, Optional
from urllib.parse import unquote

import requests

from heyreg.log import log
from heyreg.paths import ROOT, ensure_grok_on_path
from heyreg.stop import raise_if_stop

HEYGEN_HINTS = (
    "heygen",
    "movio",
    "verify",
    "verification",
    "confirm",
    "one-time",
    "otp",
    "security code",
)
CODE_RE = re.compile(r"\b(\d{4,8})\b")
LINK_RE = re.compile(
    r"https?://(?:auth|app|api2|m)\.heygen\.com/[^\s\"'<>]*(?:verify|confirm|magic|token|login)[^\s\"'<>]*",
    re.I,
)
ANY_HEYGEN_LINK = re.compile(
    r"https?://(?:auth|app|api2)\.heygen\.com/[^\s\"'<>]{8,}",
    re.I,
)
_SKIP_CODE = {"000000", "123456", "111111", "999999"}


def _blob_is_heygen(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in HEYGEN_HINTS)


def extract_heygen_proof(text: str) -> dict[str, str]:
    raw = unquote(text or "")
    out: dict[str, str] = {}
    m = LINK_RE.search(raw) or ANY_HEYGEN_LINK.search(raw)
    if m:
        link = m.group(0).rstrip(").,]>\"'")
        low = link.lower()
        if not any(x in low for x in (".css", ".js", ".woff", "static.heygen", "/asset/", ".png", ".svg")):
            out["link"] = link
    codes = CODE_RE.findall(raw)
    for c in codes:
        if c.startswith("20") and len(c) == 4:
            continue
        if c in _SKIP_CODE:
            continue
        if len(c) < 4:
            continue
        out["code"] = c
        break
    return out


def acquire_email(config: dict[str, Any]):
    grok = ensure_grok_on_path()
    if not grok:
        raise RuntimeError("Khong thay folder grok_tool — can de Heygen canh grok_tool de dung mail")

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
    want = str(config.get("email_provider") or "azpopmail").strip().lower()
    if want in ("tmail", "3"):
        want = "tmail_wibu"
    if want in ("5", "custom", "custom_domain", "domain", "rieng"):
        want = "custom_domain"
    if want not in ("hotmail", "azpopmail", "tmail_wibu", "custom_domain"):
        want = "azpopmail"
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
    tmail_cfg = dict(merged.get("tmail_wibu") or grok_cfg.get("tmail_wibu") or {})
    if want == "tmail_wibu":
        # domain bi ban (khong nhan mail HeyGen) -> skip; domain lich su tot chay truoc
        import json as _json
        banned: list[str] = []
        try:
            banned = [d for d in _json.loads((ROOT / "data" / "tmail_banned.json").read_text(encoding="utf-8")) if isinstance(d, str)]
        except Exception:
            banned = []
        known_bad = ["adon.name.ng", "ames.name.ng", "adix.name.ng"]  # lich su HeyGen 0/7
        skip = {d.lower() for d in (banned + known_bad)}
        cur_skip = [d for d in (tmail_cfg.get("skip_domains") or []) if isinstance(d, str)]
        tmail_cfg["skip_domains"] = list({*cur_skip, *skip})
        doms = [d for d in (tmail_cfg.get("domains") or []) if str(d).lower() not in skip]
        if doms:
            tmail_cfg["domains"] = doms
        log.info("tmail HeyGen: %s domain sau khi loc ban %s", len(doms), sorted(skip) or "—")
    tmail = TmailWibuProvider(tmail_cfg)
    session, hotmail = acquire_email_session(merged, mailtm, azpop, tmail_wibu=tmail)
    addr = str(getattr(session, "address", "") or "").lower()
    if want == "azpopmail" and (addr.endswith(".name.ng") or "wibucrypto" in addr):
        # chi doi sang azpop khi dang chay che do azpop ma nhan tmail
        # (che do tmail_wibu chu dong giu dia chi .name.ng)
        log.warning("Bo mail spam %s — tao azpop", addr)
        session = azpop.create()
        hotmail = None
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
        "&$select=id,subject,from,body,bodyPreview,receivedDateTime$select=id,subject,from,toRecipients,ccRecipients,body,bodyPreview,receivedDateTime",
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
            str(m.get("from") or ""),
        ]
    )


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


def wait_heygen_mail(
    session,
    config: dict[str, Any],
    *,
    mail_api=None,
    hotmail=None,
    azpop=None,
    tmail=None,
    mailtm=None,
    timeout: int = 180,
) -> dict[str, str]:
    """Return {code?, link?} from a HeyGen verification mail."""
    deadline = time.time() + max(30, int(timeout))
    provider = str(getattr(session, "provider", "") or "")
    cid = str((config.get("mail_api") or {}).get("client_id") or "")
    log.info("Cho mail HeyGen (%s, timeout=%ss)…", provider, timeout)

    while time.time() < deadline:
        raise_if_stop()
        try:
            if provider in ("hotmail", "custom_domain"):
                target = (
                    str(getattr(session, "address", "") or "").lower()
                    if provider == "custom_domain"
                    else ""
                )
                for m in _graph_messages(session, cid):
                    blob = _msg_text(m)
                    if not _blob_is_heygen(blob):
                        continue
                    if target and not _msg_to(m, target):
                        continue
                    proof = extract_heygen_proof(blob)
                    if proof:
                        log.info("HeyGen mail: %s", proof)
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
                    except Exception as e:
                        log.warning("azpop message_body fail (mid=%s): %s — OTP có thể bị sót", mid, e)
                    blob = f"{m.get('subject','')} {m.get('from','')} {body}"
                    if not _blob_is_heygen(blob):
                        continue
                    proof = extract_heygen_proof(blob)
                    if proof:
                        log.info("HeyGen mail: %s", proof)
                        return proof
            elif provider == "tmail_wibu" and tmail:
                extra = dict(getattr(session, "extra", None) or {})
                page_otp, page_html, _ = tmail._scrape_mailbox_page(extra)
                blob = page_html or ""
                if page_otp:
                    blob = f"{blob} {page_otp}"
                try:
                    messages, html_blob = tmail._fetch_messages(session.address, extra)
                    blob = f"{blob} {html_blob or ''}"
                    for msg in messages or []:
                        blob += " " + tmail._msg_blob(msg)
                        mid = str(msg.get("id") or "")
                        if mid and hasattr(tmail, "_open_message"):
                            try:
                                blob += " " + (tmail._open_message(session.address, extra, mid) or "")
                            except Exception as e:
                                log.warning("tmail open_message fail (mid=%s): %s — đọc OTP thiếu body", mid, e)
                except Exception as e:
                    log.debug("tmail fetch: %s", e)
                proof = extract_heygen_proof(blob)
                if proof:
                    log.info("HeyGen mail (tmail): %s", proof)
                    return proof
            elif mailtm:
                otp = mailtm.wait_otp(session, timeout=8)
                if otp:
                    return {"code": otp}
        except Exception as e:
            log.debug("mail poll: %s", e)
        time.sleep(3)
    return {}
