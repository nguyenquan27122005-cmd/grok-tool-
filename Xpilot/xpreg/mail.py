"""Acquire inbox cho X-Pilot + wait OTP generic.

X-Pilot KHÔNG chặn domain temp (đã test tmail wibu) nhưng BẮT BUỘC email
verification (OTP 6 số). Route OTP theo provider:
  hotmail/custom_domain → HotmailProvider Graph/IMAP (generic, không lọc sender xAI)
  azpopmail/tmail_wibu/tmail_spectxte/mailtm → wait_otp riêng của từng provider
(Không dùng MailApiClient/wait_otp_smart vì chúng lọc cứng mail x.ai/grok.)
"""

from __future__ import annotations

from typing import Any, Optional

from xpreg.log import log
from xpreg.paths import ROOT, ensure_grok_on_path


def acquire_email(config: dict[str, Any]):
    grok = ensure_grok_on_path()
    if not grok:
        raise RuntimeError("Khong thay folder grok_tool — can dat Xpilot canh grok_tool de dung mail")

    from grokreg.core.config import load_config as load_grok_cfg
    from grokreg.mail.mail_api import MailApiClient
    from grokreg.mail.providers import AzpopMailProvider, HotmailProvider, MailTmProvider
    from grokreg.mail.tmail_spectxte import TmailSpectxteProvider
    from grokreg.mail.tmail_wibu import TmailWibuProvider
    from grokreg.reg.flow import acquire_email_session

    grok_cfg = {}
    try:
        grok_cfg = load_grok_cfg()
    except Exception:
        grok_cfg = {}

    merged = dict(grok_cfg)
    merged.update(config)
    want = str(config.get("email_provider") or "auto_temp").strip().lower()
    if want in ("tmail", "3"):
        want = "tmail_wibu"
    if want in ("4", "spectxte", "tmail_spectxte"):
        want = "tmail_spectxte"
    if want in ("5", "custom", "custom_domain", "domain", "rieng"):
        want = "custom_domain"
    if want not in ("hotmail", "azpopmail", "tmail_wibu", "tmail_spectxte", "custom_domain", "auto_temp", "mailtm"):
        want = "auto_temp"
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
    spectxte = TmailSpectxteProvider(
        dict(merged.get("tmail_spectxte") or grok_cfg.get("tmail_spectxte") or {})
    )
    session, hotmail = acquire_email_session(
        merged, mailtm, azpop, tmail_wibu=tmail, tmail_spectxte=spectxte
    )
    if str(config.get("email_provider") or "") in ("hotmail", "1") and session.provider == "auto_temp":
        log.info("hotmail pool rỗng — dùng temp mail %s", session.address)
    return session, hotmail, MailApiClient(merged.get("mail_api") or {}), azpop, tmail, mailtm, spectxte


def wait_otp_any(
    session: Any,
    *,
    hotmail: Optional[Any],
    mail_api: Any,
    azpop: Any,
    tmail: Any,
    mailtm: Any,
    spectxte: Any,
    timeout: int = 180,
) -> Optional[str]:
    """OTP 6 số cho X-Pilot — route theo provider của session (generic, mọi sender)."""
    prov = str(getattr(session, "provider", "") or "")
    if prov in ("hotmail", "custom_domain"):
        if not hotmail:
            log.error("provider %s nhưng không có HotmailProvider", prov)
            return None
        return hotmail.wait_otp(session, timeout=timeout)
    if prov == "azpopmail":
        return azpop.wait_otp(session, timeout=timeout)
    if prov == "tmail_wibu":
        return tmail.wait_otp(session, timeout=timeout)
    if prov == "tmail_spectxte":
        return spectxte.wait_otp(session, timeout=timeout)
    return mailtm.wait_otp(session, timeout=timeout)
