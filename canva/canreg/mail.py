"""Inbox via grok_tool Hotmail / Azpop / Guerrilla. Canva gửi OTP 'Your Canva code'."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import unquote

import requests

from canreg.log import log
from canreg.paths import ROOT, ensure_grok_on_path
from canreg.stop import raise_if_stop

HINTS = (
    "canva",
    "your canva code",
    "your login code",
    "login code",
    "verification",
    "verify",
    "confirm",
    "one-time",
    "otp",
    "security code",
    "sign up",
    "signup",
)
CODE_RE = re.compile(r"\b(\d{6})\b")
CODE_LABELED = re.compile(
    r"(?:your canva code|your login code|verification code|login code|code is|otp|mã(?:\s+xác\s+nhận)?)"
    r"\s*(?:is|:)?\s*(\d{4,8})",
    re.I,
)
SUBJ_CODE = re.compile(
    r"your (?:canva|login) code is\s+(\d{6})",
    re.I,
)
ENTER_CODE = re.compile(r"enter\s+(\d{6})\s+in the next", re.I)
LINK_RE = re.compile(
    r"https?://(?:www\.)?canva\.com/[^\s\"'<>]*(?:verify|confirm|login|signup|code|token)[^\s\"'<>]*",
    re.I,
)
_SKIP = {"000000", "123456", "111111", "999999"}
GUERRILLA_API = "https://api.guerrillamail.com/ajax.php"


def _is_canva_mail(text: str, from_addr: str = "") -> bool:
    low = f"{text or ''} {from_addr or ''}".lower()
    if "canva.com" in low or "canva" in low:
        return True
    if "login code" in low or "your canva code" in low:
        return True
    return any(h in low for h in HINTS)


def _clean_code(raw: str) -> str:
    c = str(raw or "").strip()
    if not c or c in _SKIP:
        return ""
    if c.startswith("20") and len(c) == 6:
        return ""
    if not c.isdigit() or len(c) < 4 or len(c) > 8:
        return ""
    return c


def _plain_text(text: str) -> str:
    """HTML Livewire/tmail → text. Giữ câu 'Your Canva code is 123456'."""
    t = unquote(text or "")
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?is)<br\s*/?>", "\n", t)
    t = re.sub(r"(?is)</(p|div|h[1-6]|li|tr|td|span)>", "\n", t)
    t = re.sub(r"(?is)<[^>]+>", " ", t)
    t = (
        t.replace("&nbsp;", " ")
        .replace("&#160;", " ")
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"[ \t]+", " ", t).strip()


def _fresh_proof(proof: dict[str, str] | None, skip: set[str]) -> dict[str, str]:
    if not proof:
        return {}
    code = str(proof.get("code") or "")
    if code and code in skip:
        return {}
    return proof


def extract_proof(text: str, *, subject: str = "") -> dict[str, str]:
    """OTP chỉ lấy từ câu Canva gán nhãn — không lấy số rác HTML.

    Tìm trên subject + toàn bộ text đã strip HTML. Không cắt [:500]:
    tmail ghép cả trang Livewire nên OTP nằm sâu, 500 ký tự đầu chỉ là <head>.
    """
    subj = unquote(subject or "")
    raw = unquote(text or "")
    plain = _plain_text(raw)
    out: dict[str, str] = {}
    m = LINK_RE.search(raw) or LINK_RE.search(subj) or LINK_RE.search(plain)
    if m:
        link = m.group(0).rstrip(").,]>\"'")
        if not any(x in link.lower() for x in (".css", ".js", ".png", ".svg", "/static/")):
            out["link"] = link
    for src in (subj, plain, raw):
        if not src:
            continue
        for rx in (SUBJ_CODE, ENTER_CODE, CODE_LABELED):
            m = rx.search(src)
            if not m:
                continue
            code = _clean_code(m.group(1))
            if code:
                out["code"] = code
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
        raise RuntimeError("Thiếu folder grok_tool cạnh canva — cần mail")

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
    if want in ("3", "tmail", "tmail_wibu", "tmailwibu", "wibu"):
        want = "tmail_wibu"
    elif want in ("2", "azpop", "azpopmail"):
        want = "azpopmail"
    elif want in ("1", "hotmail", "outlook", "ms"):
        want = "hotmail"
    elif want in ("4", "guerrilla", "guerrillamail"):
        want = "guerrilla"
    elif want in ("0", "auto_temp", "temp", "smart"):
        want = "auto_temp"
    elif want in ("5", "custom_domain", "custom", "domain", "rieng"):
        want = "custom_domain"
    elif want not in ("hotmail", "azpopmail", "tmail_wibu", "guerrilla", "auto_temp", "custom_domain"):
        want = "hotmail"
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
    tmail_cfg = dict(grok_cfg.get("tmail_wibu") or {})
    tmail_cfg.update(config.get("tmail_wibu") or {})
    if want == "tmail_wibu":
        from canreg.tmail_policy import apply_to_tmail_cfg

        tmail_cfg = apply_to_tmail_cfg(
            tmail_cfg,
            hunt_new=bool(config.get("tmail_hunt_new")),
        )
        log.info(
            "tmail pool Canva còn %s domain%s",
            len(tmail_cfg.get("domains") or []),
            " (hunt domain mới)" if config.get("tmail_hunt_new") else "",
        )
    merged["tmail_wibu"] = tmail_cfg
    tmail = TmailWibuProvider(tmail_cfg)
    guerrilla = GuerrillaMail()
    if want == "guerrilla":
        session = guerrilla.create()
        hotmail = None
    else:
        session, hotmail = acquire_email_session(merged, mailtm, azpop, tmail_wibu=tmail)
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
    # Login code Canva (no-reply@account.canva.com) hay rơi vào Junk —
    # poll cả inbox lẫn junkemail, gộp kết quả (reg code thì vào Inbox).
    sel = (
        "?$top=20&$orderby=receivedDateTime desc"
        "&$select=id,subject,from,toRecipients,body,bodyPreview,"
        "receivedDateTime,createdDateTime,sentDateTime"
    )
    msgs: list[dict[str, Any]] = []
    for folder in ("inbox", "junkemail"):
        r = requests.get(
            f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages{sel}",
            headers={"Authorization": "Bearer " + access},
            timeout=25,
        )
        if r.status_code == 200:
            msgs.extend((r.json() or {}).get("value") or [])
    return msgs


def _msg_epoch(m: dict[str, Any]) -> float:
    raw = str(m.get("receivedDateTime") or m.get("received") or "").strip()
    if not raw:
        return 0.0
    try:
        from datetime import datetime

        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _msg_recipients(m: dict[str, Any]) -> str:
    out: list[str] = []
    for key in ("toRecipients", "ccRecipients"):
        for item in m.get(key) or []:
            if isinstance(item, dict):
                addr = str((item.get("emailAddress") or {}).get("address") or "").strip()
                if addr:
                    out.append(addr)
    return " ".join(out)


def _mail_for_target(m: dict[str, Any], target: str) -> bool:
    """Chỉ nhận mail gửi tới đúng acc đang signup (kể cả +1)."""
    want = (target or "").strip().lower()
    if not want:
        return True
    recips = _msg_recipients(m).lower()
    subj = str(m.get("subject") or "").lower()
    prev = str(m.get("bodyPreview") or "").lower()
    blob = f"{recips} {subj} {prev} {_msg_text(m)}".lower()
    if want in recips or want in blob:
        return True
    local, _, domain = want.partition("@")
    if "+" in local:
        return False
    if re.search(rf"{re.escape(local)}\+\d+@{re.escape(domain)}", blob):
        return False
    return want in recips


def _best_hotmail_proof(
    messages: list[dict[str, Any]],
    *,
    since_ts: float,
    skip: set[str],
    target: str,
) -> tuple[dict[str, str], dict[str, Any], float] | None:
    cands: list[tuple[float, int, dict[str, str], dict[str, Any]]] = []
    for i, m in enumerate(messages):
        ts = _msg_epoch(m)
        if ts and ts < since_ts:
            continue
        if not _mail_for_target(m, target):
            continue
        subj = str(m.get("subject") or "")
        frm = str(((m.get("from") or {}).get("emailAddress") or {}).get("address") or "")
        blob = f"{subj} {frm} {_msg_text(m)}"
        if not _is_canva_mail(blob, frm) and "canva code" not in subj.lower() and "login code" not in subj.lower():
            continue
        proof = extract_proof(blob, subject=subj)
        code = str((proof or {}).get("code") or "")
        if not proof or (code and code in skip):
            continue
        cands.append((ts, i, proof, m))
    if not cands:
        return None

    def _stamp(item: tuple) -> tuple:
        _ts, _i, _proof, msg = item
        created = _msg_epoch({"receivedDateTime": msg.get("createdDateTime") or ""})
        sent = _msg_epoch({"receivedDateTime": msg.get("sentDateTime") or ""})
        mid = str(msg.get("id") or "")
        return (_ts, created, sent, mid)

    # Mới nhất theo received → created → sent → id (cùng giây lấy mã phát sau)
    cands.sort(key=_stamp, reverse=True)
    ts, _i, proof, m = cands[0]
    return proof, m, ts


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


def wait_canva_mail(
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
    since: float | None = None,
    ignore_codes: set[str] | None = None,
    require_login_subject: bool = False,
) -> dict[str, str]:
    deadline = time.time() + max(30, int(timeout))
    provider = str(getattr(session, "provider", "") or "")
    cid = str((config.get("mail_api") or {}).get("client_id") or "")
    since_ts = float(since) if since is not None else (time.time() - 45)
    skip = ignore_codes if isinstance(ignore_codes, set) else set(ignore_codes or ())
    log.info("Chờ mail Canva (%s, timeout=%ss, chỉ mail mới)…", provider, timeout)
    last_ping = 0.0
    last_inbox = ""

    while time.time() < deadline:
        raise_if_stop()
        try:
            if provider == "guerrilla" and guerrilla:
                for m in guerrilla.list_messages(session) or []:
                    subj = str(m.get("mail_subject") or "")
                    frm = str(m.get("mail_from") or "")
                    if "guerrilla" in (subj + frm).lower() and "canva" not in (subj + frm).lower():
                        continue
                    body = ""
                    mid = str(m.get("mail_id") or "")
                    if mid:
                        try:
                            body = guerrilla.fetch_body(session, mid)
                        except Exception as e:
                            log.warning("guerrilla fetch_body fail (mid=%s): %s — OTP có thể bị sót", mid, e)
                    proof = extract_proof(f"{subj} {frm} {body}")
                    if proof:
                        log.info("Canva Guerrilla: %s (%s)", proof, subj[:80])
                        return proof
            elif provider in ("hotmail", "custom_domain"):
                target = str(getattr(session, "address", "") or "")
                picked = _best_hotmail_proof(
                    _graph_messages(session, cid),
                    since_ts=since_ts,
                    skip=skip,
                    target=target,
                )
                if picked:
                    # Canva hay gửi 2 mã cùng giây — đợi 3s lấy cái đứng trước (mới)
                    if time.time() + 3 < deadline:
                        time.sleep(3)
                        again = _best_hotmail_proof(
                            _graph_messages(session, cid),
                            since_ts=since_ts,
                            skip=skip,
                            target=target,
                        )
                        if again:
                            picked = again
                    best, msg, _ts = picked
                    recips = _msg_recipients(msg)
                    log.info(
                        "Canva %s MỚI NHẤT: %s to=%s subj=%s received=%s",
                        provider,
                        best,
                        recips or "?",
                        str(msg.get("subject") or "")[:60],
                        msg.get("receivedDateTime") or "?",
                    )
                    code = str(best.get("code") or "")
                    if code:
                        skip.add(code)
                    return best
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
                    if not _is_canva_mail(blob) and not extract_proof(blob):
                        continue
                    proof = extract_proof(blob)
                    if proof:
                        log.info("Canva Azpop: %s", proof)
                        return proof
            elif provider == "tmail_wibu" and tmail:
                extra = dict(getattr(session, "extra", None) or {})
                page_html = ""
                html_blob = ""
                messages: list[dict[str, Any]] = []
                try:
                    _, page_html, page_email = tmail._scrape_mailbox_page(extra)
                    if page_email and page_email.lower() != str(session.address or "").lower():
                        last_inbox = f"page email={page_email} ≠ {session.address}"
                        log.info("tmail page email %s != session %s", page_email, session.address)
                except Exception as e:
                    last_inbox = f"scrape lỗi: {e}"
                    log.info("tmail scrape lỗi: %s", e)
                try:
                    messages, html_blob = tmail._fetch_messages(session.address, extra)
                    subjects = []
                    reg_mail_re = re.compile(r"your canva code is|verify your email", re.I)
                    for msg in messages or []:
                        if require_login_subject and reg_mail_re.search(
                            str(msg.get("subject") or "")
                        ):
                            # Đang lấy OTP đăng nhập — mã reg cũ trong hộp
                            # (nhánh tmail không lọc theo since) phải bỏ qua.
                            continue
                        subj = str(msg.get("subject") or msg.get("from") or "")[:80]
                        blob = tmail._msg_blob(msg)
                        proof = _fresh_proof(
                            extract_proof(blob, subject=str(msg.get("subject") or "")),
                            skip,
                        )
                        if proof:
                            code = str(proof.get("code") or "")
                            if code:
                                skip.add(code)
                            log.info("Canva tmail msg: %s subj=%s", proof, subj)
                            return proof
                        mid = str(msg.get("id") or msg.get("uid") or "")
                        if mid and hasattr(tmail, "_open_message"):
                            try:
                                opened = tmail._open_message(session.address, extra, mid) or ""
                            except Exception as e:
                                opened = ""
                                log.info("tmail open %s: %s", mid, e)
                            if opened:
                                proof = _fresh_proof(
                                    extract_proof(opened, subject=str(msg.get("subject") or "")),
                                    skip,
                                )
                                if proof:
                                    code = str(proof.get("code") or "")
                                    if code:
                                        skip.add(code)
                                    log.info("Canva tmail open: %s id=%s", proof, mid)
                                    return proof
                        if subj:
                            subjects.append(subj)
                    n = len(messages or [])
                    empty = "Empty Inbox" in ((page_html or "") + (html_blob or ""))
                    if n:
                        last_inbox = f"{n} mail, subj={subjects[:3] or ['(không subject)']}"
                    elif empty:
                        last_inbox = "inbox trống"
                    else:
                        last_inbox = "0 mail (Livewire chưa list)"
                except Exception as e:
                    last_inbox = f"fetch lỗi: {e}"
                    log.info("tmail fetch lỗi: %s", e)
                for chunk, label in (
                    (page_html, "page"),
                    (html_blob, "livewire"),
                ):
                    if not chunk:
                        continue
                    proof = _fresh_proof(extract_proof(chunk), skip)
                    if proof:
                        code = str(proof.get("code") or "")
                        if code:
                            skip.add(code)
                        log.info("Canva tmail %s: %s", label, proof)
                        return proof
            elif mailtm:
                otp = mailtm.wait_otp(session, timeout=8)
                if otp:
                    proof = extract_proof(str(otp))
                    if proof:
                        return proof
        except Exception as e:
            log.debug("mail poll: %s", e)
        left = int(deadline - time.time())
        if time.time() - last_ping >= 15:
            extra = f" — {last_inbox}" if last_inbox else ""
            log.info("…chưa thấy mail Canva, còn ~%ss%s", max(0, left), extra)
            last_ping = time.time()
        time.sleep(2)
    return {}
