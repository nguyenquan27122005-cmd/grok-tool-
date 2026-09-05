"""
Temp mail client for https://tmail.spectxte.bond — private REST API.

Auth: Bearer = web login password (key từ admin). Catch-all mailbox:
mọi địa chỉ user@<domain> nhận thư ngay, KHÔNG cần tạo hộp.

  GET /api/domains                       → {"ok":true,"domains":[...]}
  GET /api/inbox?addr=user@domain        → {"ok":true,"emails":[...]}
  GET /api/mail/:id                      → full mail detail (chưa dùng)
  GET /api/wait?addr=…&since=ms          → long-poll (dùng /api/inbox poll ngắn thay thế)
"""

from __future__ import annotations

import logging
import random
import re
import string
import time
from typing import Any, Optional

import requests

log = logging.getLogger("grok-reg")

DEFAULT_BASE = "https://tmail.spectxte.bond"


class TmailSpectxteProvider:
    """
    Temp mail via tmail.spectxte.bond REST API (Bearer web password).

    create()  → random user@domain (catch-all, không cần đăng ký)
    wait_otp() → poll /api/inbox, extract mã xAI từ subject/body
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        self.base = str(cfg.get("base_url") or DEFAULT_BASE).rstrip("/")
        self.key = str(cfg.get("token") or cfg.get("api_key") or "").strip()
        if not self.key:
            raise RuntimeError(
                "TmailSpectxte: thiếu API key — set config tmail_spectxte.token "
                "(password web của account dos9)"
            )
        self.verify_ssl = bool(cfg.get("verify_ssl", True))
        self.poll_interval = float(cfg.get("poll_interval") or 3)
        pref = cfg.get("domains") or cfg.get("preferred_domains") or []
        if isinstance(pref, str):
            pref = [p.strip() for p in pref.split(",") if p.strip()]
        self.preferred_domains = [str(d).strip().lower() for d in pref if str(d).strip()]
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
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Authorization": f"Bearer {self.key}",
            }
        )

    def list_domains(self) -> list[str]:
        r = self._http.get(f"{self.base}/api/domains", timeout=20)
        r.raise_for_status()
        payload = r.json() or {}
        if not payload.get("ok"):
            raise RuntimeError(f"TmailSpectxte /api/domains: {payload}")
        return [str(d).strip().lower() for d in (payload.get("domains") or []) if d]

    def _pick_domain(self, live: list[str]) -> str:
        live = [d for d in live if d]
        pool = [d for d in self.preferred_domains if d in live] or list(live)
        if not pool:
            raise RuntimeError("TmailSpectxte: no domains available")
        try:
            from grokreg.browser.anti_flag import pick_diverse_domain

            choice = pick_diverse_domain(pool)
        except Exception:
            choice = random.choice(pool)
        log.info("TmailSpectxte domain pick: %s (live=%s)", choice, live)
        return choice

    @staticmethod
    def _random_user(n: int = 10) -> str:
        first = random.choice(string.ascii_lowercase)
        rest = "".join(random.choices(string.ascii_lowercase + string.digits, k=n - 1))
        return first + rest

    @staticmethod
    def _trust_otp(
        otp: str, subject: str, frm: str, preview: str, body: str
    ) -> bool:
        """
        Catch-all domain nhận mọi mail — spam 6 số không được nhầm thành OTP.
        Dashed alnum (YI2-BKR) chấp nhận luôn; code thuần số phải có dấu hiệu xAI.
        """
        blob = f"{subject} {frm} {preview} {body}"
        try:
            from grokreg.core.helpers import is_plausible_xai_otp

            if not is_plausible_xai_otp(otp):
                return False
        except Exception:
            pass
        if re.fullmatch(r"[A-Z0-9]{2,5}-[A-Z0-9]{2,5}", otp or "", re.I):
            return True
        return bool(
            re.search(r"x\.ai|grok|spacexai|noreply", blob, re.I)
        ) or bool(re.search(r"verif|confirm|security code|your code", blob, re.I))

    # ------------------------------------------------------------------
    # Inbox
    # ------------------------------------------------------------------

    def _inbox(self, address: str) -> list[dict[str, Any]]:
        r = self._http.get(
            f"{self.base}/api/inbox",
            params={"addr": address, "limit": 100},
            timeout=25,
        )
        r.raise_for_status()
        payload = r.json() or {}
        if not payload.get("ok"):
            raise RuntimeError(f"TmailSpectxte /api/inbox: {str(payload)[:120]}")
        emails = payload.get("emails") or []
        return [e for e in emails if isinstance(e, dict)]

    def _message_body(self, msg_id: Any) -> str:
        try:
            r = self._http.get(f"{self.base}/api/mail/{msg_id}", timeout=20)
            if r.status_code != 200:
                return ""
            payload = r.json() or {}
            if not payload.get("ok"):
                return ""
            data = payload.get("mail") or payload.get("email") or payload
            return " ".join(
                str(data.get(k) or "")
                for k in ("subject", "from", "text", "html", "body", "content")
            )
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # EmailSession API
    # ------------------------------------------------------------------

    def create(self) -> Any:
        from grokreg.mail.mail_api import EmailSession

        domain = self._pick_domain(self.list_domains())
        username = self._random_user()
        address = f"{username}@{domain}"
        try:
            self._inbox(address)
        except Exception as e:
            raise RuntimeError(f"TmailSpectxte create failed for {address}: {e}") from e
        log.info("TmailSpectxte ready: %s  (base=%s)", address, self.base)
        return EmailSession(
            address=address,
            password="",
            provider="tmail_spectxte",
            token=self.key,
            extra={"base_url": self.base, "domain": domain},
        )

    def create_mailbox(self) -> tuple[str, dict[str, Any]]:
        """Same shape as TmailWibuProvider.create_mailbox."""
        session = self.create()
        return session.address, dict(session.extra)

    def wait_otp(
        self,
        session: Any,
        timeout: int = 180,
        *,
        ignore_ids: set[str] | None = None,
    ) -> Optional[str]:
        try:
            from grokreg.core.helpers import extract_otp, normalize_otp_for_input
            from grokreg.core.stop_control import raise_if_stop, sleep_interruptible
        except Exception:
            extract_otp = None  # type: ignore[assignment]
            normalize_otp_for_input = lambda otp: re.sub(  # noqa: E731
                r"[^A-Za-z0-9]", "", otp or ""
            ).upper()

            def sleep_interruptible(sec: float) -> None:  # type: ignore[misc]
                time.sleep(sec)

            def raise_if_stop() -> None:  # type: ignore[misc]
                return None

        address = str(getattr(session, "address", "") or "")
        if "@" not in address:
            raise RuntimeError(f"TmailSpectxte: invalid session address {address!r}")

        deadline = time.time() + timeout
        t0 = time.time()
        log.info(
            "Waiting OTP via TmailSpectxte %s for %s (max %ss)...",
            self.base,
            address,
            timeout,
        )
        seen: set[str] = set(ignore_ids or set())
        poll_i = 0
        consecutive_err = 0

        while time.time() < deadline:
            poll_i += 1
            try:
                raise_if_stop()
                msgs = self._inbox(address)
                consecutive_err = 0
                if msgs:
                    log.info(
                        "TmailSpectxte inbox %s msg(s) — newest subj=%r",
                        len(msgs),
                        str(msgs[0].get("subject") or "")[:60],
                    )
                elif poll_i % 5 == 0:
                    log.info(
                        "TmailSpectxte still empty for %s (%.0fs) poll=%s",
                        address,
                        time.time() - t0,
                        poll_i,
                    )
                for msg in msgs:
                    mid = str(msg.get("id") or msg.get("mail_id") or "")
                    if not mid or mid in seen:
                        continue
                    seen.add(mid)
                    subject = str(msg.get("subject") or "")
                    frm = str(msg.get("from") or msg.get("sender") or "")
                    preview = str(msg.get("preview") or msg.get("text") or "")
                    # subject thường mang mã — thử trước khi tốn call body
                    otp = extract_otp(subject) if extract_otp else None
                    if not otp and extract_otp:
                        otp = extract_otp(f"{subject} {frm} {preview}")
                    body = ""
                    if not otp:
                        body = self._message_body(mid)
                        if body:
                            otp = extract_otp(body)
                    if not otp:
                        continue
                    if not self._trust_otp(otp, subject, frm, preview, body):
                        log.info(
                            "TmailSpectxte skip non-xAI mail id=%s subj=%r otp=%s",
                            mid,
                            subject[:60],
                            otp,
                        )
                        continue
                    elapsed = time.time() - t0
                    log.info(
                        "OTP found (TmailSpectxte): display=%s input=%s id=%s subj=%r (%.1fs)",
                        otp,
                        normalize_otp_for_input(otp),
                        mid,
                        subject[:50],
                        elapsed,
                    )
                    session.extra = dict(getattr(session, "extra", None) or {})
                    return otp
            except Exception as e:
                if e.__class__.__name__ in ("StopRequested",):
                    raise
                consecutive_err += 1
                log.warning(
                    "TmailSpectxte poll error (%s): %s", consecutive_err, e
                )
                if consecutive_err >= 5:
                    raise RuntimeError(
                        f"TmailSpectxte inbox fail x5: {e}"
                    ) from e
            try:
                sleep_interruptible(self.poll_interval + random.uniform(0.3, 1.2))
            except Exception:
                time.sleep(self.poll_interval + random.uniform(0.3, 1.2))

        log.error("TmailSpectxte OTP timeout after %ss for %s", timeout, address)
        return None
