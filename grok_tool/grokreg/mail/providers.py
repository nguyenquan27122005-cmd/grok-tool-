"""Auto-split from main.py — modular package."""
from __future__ import annotations

import argparse
import asyncio
import email as email_lib
import imaplib
import json
import logging
import os
import random
import re
import string
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions

import grokreg.browser.anti_flag as af
from grokreg.mail.tmail_wibu import TmailWibuProvider
import grokreg.mail.temp_mail_router as tmr
import grokreg.browser.chrome_cleanup as chrome_clean
import grokreg.core.style_log as slog
from grokreg.core.stop_control import (
    StopRequested,
    clear_stop,
    interruptible_sleep,
    is_stop_requested,
    raise_if_stop,
    request_stop,
    sleep_interruptible,
    start_esc_listener,
    stop_reason,
)

from grokreg.core.runtime import (
    ROOT,
    DATA_DIR,
    CONFIG_PATH,
    log,
    MS_CLIENT_IDS,
    FIRST_NAMES,
    LAST_NAMES,
    RATE_LIMIT_PATH,
)


from grokreg.mail.mail_api import (
    EmailSession,
    MailApiClient,
    _normalize_mail_item,
    _msg_blob,
    _is_xai_mail,
    _extract_otp_strict,
    _otp_from_mail_payload,
)
from grokreg.core.helpers import extract_otp, normalize_otp_for_input
from grokreg.core.config import load_config

class MailTmProvider:
    BASE = "https://api.mail.tm"

    def create(self) -> EmailSession:
        try:
            domains = requests.get(f"{self.BASE}/domains", timeout=15).json()["hydra:member"]
            domain = domains[0]["domain"]
        except Exception as e:
            raise RuntimeError(f"Mail.tm domain fetch failed: {e}") from e

        username = random_string(10).lower()
        address = f"{username}@{domain}"
        password = random_string(14)

        r = requests.post(
            f"{self.BASE}/accounts",
            json={"address": address, "password": password},
            timeout=15,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Mail.tm create failed: {r.status_code} {r.text[:200]}")

        tr = requests.post(
            f"{self.BASE}/token",
            json={"address": address, "password": password},
            timeout=15,
        )
        if tr.status_code != 200:
            raise RuntimeError(f"Mail.tm token failed: {tr.status_code} {tr.text[:200]}")

        token = tr.json()["token"]
        log.info("Mail.tm ready: %s", address)
        return EmailSession(address=address, password=password, provider="mailtm", token=token)

    def wait_otp(self, session: EmailSession, timeout: int = 180) -> Optional[str]:
        headers = {"Authorization": f"Bearer {session.token}"}
        deadline = time.time() + timeout
        log.info("Waiting OTP via Mail.tm API (max %ss)...", timeout)
        seen: set[str] = set()

        while time.time() < deadline:
            raise_if_stop()
            try:
                msgs = requests.get(f"{self.BASE}/messages", headers=headers, timeout=12).json()
                for m in msgs.get("hydra:member", []):
                    mid = str(m.get("id", ""))
                    if mid in seen:
                        continue
                    detail = requests.get(
                        f"{self.BASE}/messages/{mid}", headers=headers, timeout=12
                    ).json()
                    seen.add(mid)
                    blob = " ".join(
                        str(detail.get(k) or "")
                        for k in ("subject", "text", "intro", "html")
                    )
                    otp = extract_otp(blob)
                    if otp:
                        log.info("OTP found (Mail.tm): %s", otp)
                        return otp
            except StopRequested:
                raise
            except Exception as e:
                log.debug("Mail.tm poll error: %s", e)
            sleep_interruptible(3)
        return None


class AzpopMailProvider:
    """
    Temp mail via https://azpopmail.com/document (TempMail VIP REST API).

      GET  /api/domain_list
      POST /messages  username + domain (+ optional token)  → list
      POST /messages  id + username + domain (+ token)       → HTML body

    No account signup: pick random username@domain, poll inbox for OTP.
    Note: server cert may not match azpopmail.com → verify_ssl default false.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        self.base = str(cfg.get("base_url") or "https://azpopmail.com").rstrip("/")
        self.auth_token = str(cfg.get("token") or cfg.get("auth_token") or "").strip()
        self.verify_ssl = bool(cfg.get("verify_ssl", False))
        pref = cfg.get("domains") or cfg.get("preferred_domains") or []
        if isinstance(pref, str):
            pref = [p.strip() for p in pref.split(",") if p.strip()]
        self.preferred_domains = [str(d).strip().lower() for d in pref if str(d).strip()]
        self.poll_interval = float(cfg.get("poll_interval") or 3)
        self._http = requests.Session()
        self._http.verify = self.verify_ssl
        if not self.verify_ssl:
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
        self._http.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/html, */*",
            }
        )

    def _form(self, username: str, domain: str, **extra: str) -> dict[str, str]:
        data = {"username": username, "domain": domain}
        data.update({k: v for k, v in extra.items() if v is not None and v != ""})
        if self.auth_token:
            data["token"] = self.auth_token
        return data

    def list_domains(self) -> list[str]:
        r = self._http.get(f"{self.base}/api/domain_list", timeout=20)
        r.raise_for_status()
        payload = r.json()
        raw = []
        if isinstance(payload, dict):
            raw = payload.get("data") or payload.get("result") or payload.get("domains") or []
        elif isinstance(payload, list):
            raw = payload
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if isinstance(item, dict):
                name = item.get("domain_name") or item.get("domain") or item.get("name") or ""
            else:
                name = str(item or "")
            name = name.strip().lower()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def _pick_domain(self) -> str:
        domains = self.list_domains()
        if not domains:
            raise RuntimeError(f"AzpopMail: no domains from {self.base}/api/domain_list")
        # Prefer short clean domains first (better xAI delivery historically)
        clean = [
            d
            for d in domains
            if d.count(".") == 1 and len(d) <= 20
        ] or list(domains)
        pool = list(clean)
        if self.preferred_domains:
            pref = [d for d in self.preferred_domains if d in domains]
            if pref:
                pool = pref + [d for d in clean if d not in pref]
            else:
                log.warning(
                    "AzpopMail preferred domains %s not in live list — rank clean",
                    self.preferred_domains,
                )
        # Diverse weighted pick (anti-flag): rotate domains, avoid last N used
        try:
            choice = af.pick_diverse_domain(pool)
        except Exception:
            ranked = af.rank_domains(pool)
            choice = ranked[0] if ranked else random.choice(pool)
            try:
                af.mark_domain_used(choice)
            except Exception:
                pass
        ranked_preview = af.rank_domains(pool)[:6]
        log.info(
            "AzpopMail domain pick: %s (from %s candidates) top=%s",
            choice,
            len(pool),
            ranked_preview,
        )
        return choice
    def _list_messages(
        self, username: str, domain: str, update: str | None = None
    ) -> tuple[list[dict[str, Any]], str]:
        data = self._form(username, domain)
        if update:
            data["update"] = update
        r = self._http.post(
            f"{self.base}/messages",
            data=data,
            timeout=20,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        # body may be JSON list or HTML string when id is set
        ctype = (r.headers.get("content-type") or "").lower()
        text = r.text or ""
        if "application/json" in ctype or text[:1] in "{[":
            try:
                payload = r.json()
            except Exception:
                return [], ""
            if isinstance(payload, dict):
                if payload.get("error") == "Auth_Token":
                    raise RuntimeError(
                        "AzpopMail Auth_Token required — set config azpopmail.token "
                        "(from domain admin panel)"
                    )
                result = payload.get("result")
                if isinstance(result, list):
                    return result, str(payload.get("server_time") or "")
                return [], str(payload.get("server_time") or "")
            if isinstance(payload, list):
                return payload, ""
        return [], ""

    def _message_body(self, username: str, domain: str, msg_id: str) -> str:
        r = self._http.post(
            f"{self.base}/messages",
            data=self._form(username, domain, id=str(msg_id)),
            timeout=20,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        text = r.text or ""
        # detail endpoint returns HTML string (sometimes quoted JSON string)
        if text[:1] == "{":
            try:
                payload = r.json()
                if isinstance(payload, dict):
                    if payload.get("error") == "Auth_Token":
                        raise RuntimeError("AzpopMail Auth_Token required for message body")
                    for k in ("html", "body", "content", "result", "message"):
                        if payload.get(k):
                            return str(payload[k])
            except RuntimeError:
                raise
            except Exception:
                pass
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            try:
                return json.loads(text)
            except Exception:
                pass
        return text

    def create(self) -> EmailSession:
        domain = self._pick_domain()
        username = random_string(10).lower()
        address = f"{username}@{domain}"
        # touch inbox so mailbox exists / API accepts address
        try:
            self._list_messages(username, domain)
        except Exception as e:
            raise RuntimeError(f"AzpopMail create/touch failed for {address}: {e}") from e
        log.info("AzpopMail ready: %s  (docs: %s/document)", address, self.base)
        return EmailSession(
            address=address,
            password="",
            provider="azpopmail",
            token=self.auth_token,
            extra={
                "username": username,
                "domain": domain,
                "base_url": self.base,
            },
        )

    def wait_otp(
        self,
        session: EmailSession,
        timeout: int = 180,
        *,
        ignore_ids: set[str] | None = None,
    ) -> Optional[str]:
        ignore_ids = ignore_ids or set()
        extra = session.extra or {}
        username = str(extra.get("username") or session.address.split("@")[0])
        domain = str(extra.get("domain") or (session.address.split("@")[1] if "@" in session.address else ""))
        if not username or not domain:
            raise RuntimeError(f"AzpopMail session missing username/domain: {session.address}")

        deadline = time.time() + timeout
        t0 = time.time()
        log.info(
            "Waiting OTP via AzpopMail %s/%s for %s (max %ss)...",
            self.base,
            "messages",
            session.address,
            timeout,
        )
        seen: set[str] = set(ignore_ids)
        server_time: str | None = None
        slow_warned = False
        poll_i = 0

        while time.time() < deadline:
            poll_i += 1
            try:
                # Every 3rd poll: full list (no update stamp) — avoids missing mail
                use_update = server_time if (poll_i % 3) else None
                msgs, st = self._list_messages(username, domain, update=use_update)
                if st:
                    server_time = st
                # newest first when API returns chronological list
                msg_list = list(msgs or [])
                try:
                    msg_list = sorted(
                        msg_list,
                        key=lambda x: str(
                            x.get("date")
                            or x.get("time")
                            or x.get("created_at")
                            or x.get("id")
                            or x.get("mail_id")
                            or ""
                        ),
                        reverse=True,
                    )
                except Exception:
                    msg_list = list(reversed(msg_list))

                if msg_list:
                    log.info(
                        "AzpopMail inbox %s msg(s) — newest subj=%r from=%r",
                        len(msg_list),
                        str(msg_list[0].get("subject") or "")[:60],
                        str(
                            msg_list[0].get("from") or msg_list[0].get("sender") or ""
                        )[:40],
                    )
                elif poll_i % 5 == 0:
                    log.info(
                        "AzpopMail still empty for %s@%s (%.0fs)",
                        username,
                        domain,
                        time.time() - t0,
                    )

                for m in msg_list:
                    mid = str(m.get("id") or m.get("mail_id") or "")
                    if not mid or mid in seen:
                        continue
                    seen.add(mid)
                    subject = str(m.get("subject") or "")
                    frm = str(m.get("from") or m.get("sender") or "")
                    body = ""
                    try:
                        body = self._message_body(username, domain, mid)
                    except Exception as e:
                        log.warning("AzpopMail body id=%s: %s", mid, e)
                    # Also extract from subject alone (code often in subject)
                    blob = f"{subject} {frm} {body}"
                    blob_plain = _clean_mail_text(blob)
                    log.info(
                        "AzpopMail mail id=%s subj=%r from=%r body_len=%s",
                        mid,
                        subject[:80],
                        frm[:50],
                        len(body or ""),
                    )
                    is_xai = _is_xai_mail(blob_plain) or _is_xai_mail(blob)
                    looks_code = bool(
                        re.search(
                            r"verif|confirm|code|x\.ai|grok|noreply",
                            blob_plain,
                            re.I,
                        )
                    )
                    # Always try extract; accept dashed codes even if filter weak
                    otp = extract_otp(blob_plain) or extract_otp(blob)
                    if otp and not (is_xai or looks_code):
                        # strong form YI2-BKR alone is enough if from-ish xAI domain
                        if not re.fullmatch(r"[A-Z0-9]{2,5}-[A-Z0-9]{2,5}", otp):
                            log.debug(
                                "AzpopMail skip non-xAI mail id=%s subj=%s otp_candidate=%s",
                                mid,
                                subject[:60],
                                otp,
                            )
                            continue
                    if otp:
                        elapsed = time.time() - t0
                        log.info(
                            "OTP found (AzpopMail): display=%s input=%s id=%s subj=%s (%.1fs)",
                            otp,
                            normalize_otp_for_input(otp),
                            mid,
                            subject[:50],
                            elapsed,
                        )
                        af.mark_domain_otp(domain, ok=True, elapsed=elapsed)
                        return otp
                # domain slow: soft-fail so ranker rotates away next run
                if not slow_warned and (time.time() - t0) > max(45.0, timeout * 0.45) and not msgs:
                    log.warning(
                        "AzpopMail domain %s slow (no messages after %.0fs) — will deprioritize next run",
                        domain,
                        time.time() - t0,
                    )
                    af.mark_domain_otp(
                        domain, ok=False, elapsed=time.time() - t0, reason="slow"
                    )
                    slow_warned = True
            except StopRequested:
                raise
            except Exception as e:
                log.warning("AzpopMail poll error: %s", e)
            # jitter poll — not perfectly periodic; ESC aborts wait
            raise_if_stop()
            sleep_interruptible(self.poll_interval + random.uniform(0.2, 1.4))
        af.mark_domain_otp(
            domain, ok=False, elapsed=time.time() - t0, reason="otp_timeout"
        )
        return None


class HotmailProvider:
    TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    TOKEN_URL_COMMON = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    GRAPH_MESSAGES = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"

    def __init__(self, list_path: Path) -> None:
        self.list_path = list_path
        self.used_path = list_path.with_name(list_path.stem + "_used" + list_path.suffix)

    def _read_lines(self) -> list[str]:
        if not self.list_path.exists():
            raise RuntimeError(f"Hotmail list not found: {self.list_path}")
        return [
            ln.strip()
            for ln in self.list_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]

    def _write_lines(self, lines: list[str]) -> None:
        self.list_path.write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )

    def mark_used(self, session: EmailSession) -> None:
        # auto mode may hold a HotmailProvider while this run used Mail.tm
        if getattr(session, "provider", "") != "hotmail":
            return
        if not self.list_path.exists():
            return
        lines = self._read_lines()
        remaining = [
            ln
            for ln in lines
            if ln.strip() != session.raw_line.strip()
            and not ln.lower().startswith(session.address.lower() + "|")
        ]
        self._write_lines(remaining)
        line = (session.raw_line or "").strip()
        if line:
            with open(self.used_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        log.info("Hotmail marked used → %s", self.used_path.name)

    def available_count(self) -> tuple[int, int]:
        """Return (usable_not_rate_limited, total_lines)."""
        lines = self._read_lines() if self.list_path.exists() else []
        usable = 0
        for raw in lines:
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) < 2:
                continue
            limited, _ = is_email_rate_limited(parts[0])
            if not limited:
                usable += 1
        return usable, len(lines)

    def acquire(self, default_client_id: str = "") -> EmailSession:
        """
        Pick first hotmail that is NOT in OTP rate-limit cooldown.
        Reuse same account after cooldown instead of burning a new one.
        """
        if not self.list_path.exists():
            raise RuntimeError(f"Hotmail list not found: {self.list_path}")
        lines = self._read_lines()
        if not lines:
            raise RuntimeError(f"No hotmail accounts left in {self.list_path}")

        skipped: list[str] = []
        for raw in lines:
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) < 2:
                log.warning("Skip invalid hotmail line: %s", raw[:60])
                continue
            address, password = parts[0], parts[1]
            limited, left = is_email_rate_limited(address)
            if limited:
                mins = max(1, left // 60)
                skipped.append(f"{address} (~{mins}m left)")
                log.info("Skip rate-limited hotmail %s (%ss left)", address, left)
                continue
            # anti-flag: skip hotmail that failed recently (OTP/UI)
            failed, left_f = af.is_mail_in_fail_cooldown(address)
            if failed:
                skipped.append(f"{address} (fail-cd ~{max(1,left_f//60)}m)")
                log.info("Skip recently-failed hotmail %s (%ss left)", address, left_f)
                continue

            refresh = parts[2] if len(parts) >= 3 else ""
            client_id = parts[3] if len(parts) >= 4 else (default_client_id or "")
            session = EmailSession(
                address=address,
                password=password,
                provider="hotmail",
                refresh_token=refresh,
                client_id=client_id,
                raw_line=raw,
                list_path=self.list_path,
            )
            log.info(
                "Hotmail acquired: %s (refresh_token=%s, client_id=%s)",
                address,
                "yes" if refresh else "no",
                (client_id[:12] + "...") if client_id else "default",
            )
            if skipped:
                log.info("Skipped rate-limited: %s", "; ".join(skipped[:5]))
            return session

        raise RuntimeError(
            "All hotmails are in OTP rate-limit cooldown. "
            f"Skipped: {', '.join(skipped[:8])}. Wait or add a new line."
        )

    def _refresh_access_token(self, refresh_token: str) -> Optional[str]:
        scopes = [
            "https://graph.microsoft.com/.default offline_access",
            "https://graph.microsoft.com/Mail.Read offline_access openid profile",
            "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
        ]
        for client_id in MS_CLIENT_IDS:
            for token_url in (self.TOKEN_URL, self.TOKEN_URL_COMMON):
                for scope in scopes:
                    try:
                        r = requests.post(
                            token_url,
                            data={
                                "client_id": client_id,
                                "grant_type": "refresh_token",
                                "refresh_token": refresh_token,
                                "scope": scope,
                            },
                            timeout=20,
                        )
                        if r.status_code == 200:
                            access = r.json().get("access_token")
                            if access:
                                log.info("Graph token OK (client=%s...)", client_id[:8])
                                return access
                    except Exception:
                        continue
        return None

    def _otp_via_graph(self, access_token: str, timeout: int) -> Optional[str]:
        headers = {"Authorization": f"Bearer {access_token}"}
        deadline = time.time() + timeout
        log.info("Waiting OTP via Microsoft Graph (max %ss)...", timeout)
        seen: set[str] = set()

        while time.time() < deadline:
            raise_if_stop()
            try:
                r = requests.get(
                    self.GRAPH_MESSAGES,
                    headers=headers,
                    params={
                        "$top": 15,
                        "$orderby": "receivedDateTime desc",
                        "$select": "id,subject,bodyPreview,body,from,receivedDateTime",
                    },
                    timeout=15,
                )
                if r.status_code == 401:
                    log.warning("Graph 401 — token invalid")
                    return None
                if r.status_code != 200:
                    sleep_interruptible(4)
                    continue

                for msg in r.json().get("value", []):
                    mid = msg.get("id", "")
                    if mid in seen:
                        continue
                    seen.add(mid)
                    subject = msg.get("subject") or ""
                    preview = msg.get("bodyPreview") or ""
                    body = (msg.get("body") or {}).get("content") or ""
                    blob = f"{subject}\n{preview}\n{body}"
                    lower = blob.lower()
                    if any(k in lower for k in ("x.ai", "xai", "grok", "verification", "code", "verify")):
                        otp = extract_otp(blob)
                        if otp:
                            log.info("OTP found (Graph): %s", otp)
                            return otp
            except StopRequested:
                raise
            except Exception as e:
                log.debug("Graph poll error: %s", e)
            sleep_interruptible(4)
        return None

    def _otp_via_imap(
        self,
        address: str,
        password: str,
        access_token: Optional[str],
        timeout: int,
    ) -> Optional[str]:
        deadline = time.time() + timeout
        log.info("Waiting OTP via IMAP outlook.office365.com (max %ss)...", timeout)

        def xoauth2_string(user: str, token: str) -> str:
            return f"user={user}\x01auth=Bearer {token}\x01\x01"

        while time.time() < deadline:
            raise_if_stop()
            mail: Optional[imaplib.IMAP4_SSL] = None
            try:
                mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
                if access_token:
                    auth_str = xoauth2_string(address, access_token)
                    mail.authenticate("XOAUTH2", lambda _: auth_str.encode())
                else:
                    mail.login(address, password)

                mail.select("INBOX")
                _, data = mail.search(None, "ALL")
                ids = data[0].split()
                for mid in reversed(ids[-20:]):
                    _, msg_data = mail.fetch(mid, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    if not isinstance(raw, (bytes, bytearray)):
                        continue
                    msg = email_lib.message_from_bytes(raw)
                    subject = str(msg.get("Subject", ""))
                    parts: list[str] = [subject]
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ("text/plain", "text/html"):
                                try:
                                    payload = part.get_payload(decode=True) or b""
                                    parts.append(payload.decode(errors="ignore"))
                                except Exception:
                                    pass
                    else:
                        try:
                            payload = msg.get_payload(decode=True) or b""
                            parts.append(payload.decode(errors="ignore"))
                        except Exception:
                            pass
                    blob = "\n".join(parts)
                    lower = blob.lower()
                    if any(k in lower for k in ("x.ai", "xai", "grok", "verification", "code", "verify")):
                        otp = extract_otp(blob)
                        if otp:
                            log.info("OTP found (IMAP): %s", otp)
                            return otp
            except StopRequested:
                raise
            except Exception as e:
                log.debug("IMAP error: %s", e)
            finally:
                if mail is not None:
                    try:
                        mail.logout()
                    except Exception:
                        pass
            sleep_interruptible(5)
        return None

    def wait_otp(self, session: EmailSession, timeout: int = 180) -> Optional[str]:
        access: Optional[str] = None
        if session.refresh_token:
            access = self._refresh_access_token(session.refresh_token)
            if access:
                otp = self._otp_via_graph(access, timeout)
                if otp:
                    return otp
                log.warning("Graph OTP failed — IMAP OAuth2 fallback")
                otp = self._otp_via_imap(
                    session.address, session.password, access, max(30, timeout // 3)
                )
                if otp:
                    return otp
            else:
                log.warning("Refresh token failed — IMAP basic auth")
        else:
            log.info("No refresh_token — IMAP basic auth")

        return self._otp_via_imap(session.address, session.password, None, timeout)


def wait_otp_smart(
    session: EmailSession,
    mail_api: MailApiClient,
    mailtm: MailTmProvider,
    hotmail: Optional[HotmailProvider],
    timeout: int,
    *,
    ignore_ids: set[str] | None = None,
    since_iso: str | None = None,
    azpop: Optional[AzpopMailProvider] = None,
    tmail_wibu: Optional[TmailWibuProvider] = None,
) -> Optional[str]:
    """
    OTP priority:
      hotmail    → mail_api — newest xAI mail only
      azpopmail  → https://azpopmail.com/document REST API
      tmail_wibu → https://tmail.wibucrypto.pro Livewire
      mailtm     → Mail.tm native API
    """
    if session.provider == "hotmail":
        if mail_api.enabled:
            otp = mail_api.wait_otp(
                session,
                timeout=timeout,
                ignore_ids=ignore_ids,
                since_iso=since_iso,
            )
            if otp:
                return otp
            log.error(
                "No NEW xAI OTP found. "
                "Check refresh_token / client_id, or resend code on page."
            )
            return None
        log.error("mail_api.enabled=false — hotmail needs mail_api")
        return None

    if session.provider == "azpopmail":
        client = azpop or AzpopMailProvider()
        return client.wait_otp(session, timeout=timeout, ignore_ids=ignore_ids)

    if session.provider == "tmail_wibu":
        client = tmail_wibu or TmailWibuProvider()
        return client.wait_otp(session, timeout=timeout, ignore_ids=ignore_ids)

    return mailtm.wait_otp(session, timeout=timeout)



