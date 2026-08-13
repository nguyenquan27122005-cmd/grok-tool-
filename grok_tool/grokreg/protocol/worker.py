"""
One-account protocol HTTP registration (competitor pure-HTTP path).

Requires Turnstile external solver (local :5072 or YesCaptcha).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional

from grokreg.core.helpers import random_name, resolve_password, save_account
from grokreg.core.runtime import ROOT, log
from grokreg.mail.mail_api import EmailSession, MailApiClient
from grokreg.mail.providers import (
    AzpopMailProvider,
    HotmailProvider,
    MailTmProvider,
    wait_otp_smart,
)
from grokreg.mail.tmail_wibu import TmailWibuProvider
from grokreg.protocol.backend import (
    ProtocolEnvironmentError,
    ProtocolRegistrationBackend,
    SignupParameterDiscovery,
    build_protocol_session,
    build_signup_payload,
    clear_identity_cookies,
    read_sso_cookie_from_session,
)
from grokreg.reg.flow import acquire_email_session

SIGNUP_URL = "https://accounts.x.ai/sign-up"


@dataclass
class ProtocolResult:
    ok: bool
    status: str
    email: str = ""
    password: str = ""
    sso: str = ""
    duration_sec: float = 0.0
    detail: str = ""


def _solve_turnstile(config: dict[str, Any], *, site_key: str, url: str) -> str:
    from grokreg.captcha.turnstile_solver_client import ExternalTurnstileSolver

    provider = ExternalTurnstileSolver.from_config(config)
    if not provider.available():
        raise RuntimeError(
            "Turnstile solver offline — bật CHAY_SOLVER (:5072) hoặc YesCaptcha "
            "(protocol bắt buộc external solver, giống đối thủ)"
        )
    return provider.solve(url=url, site_key=site_key)


def register_one_protocol(config: dict[str, Any]) -> ProtocolResult:
    """Register one Grok account via pure HTTP. Returns ProtocolResult."""
    t0 = time.time()
    email_session: Optional[EmailSession] = None
    password = resolve_password(config)
    first, last = random_name(config)
    save_path = ROOT / str(config.get("save_file") or "data/accounts.txt")

    try:
        log.info("[protocol] === START pure-HTTP reg (competitor path) ===")
        session = build_protocol_session(
            {"browser_proxy": config.get("proxy") or ""},
            user_agent=str((config.get("protocol") or {}).get("user_agent") or ""),
            impersonate=str((config.get("protocol") or {}).get("impersonate") or ""),
        )
        clear_identity_cookies(session)

        discovery = SignupParameterDiscovery(session)
        params = discovery.discover(SIGNUP_URL)
        backend = ProtocolRegistrationBackend(session, params)
        log.info(
            "[protocol] params sitekey=%s… action=%s…",
            params.site_key[:14],
            params.action_id[:12],
        )

        mailtm = MailTmProvider()
        azpop = AzpopMailProvider(config)
        tmail = TmailWibuProvider(config.get("tmail_wibu") or {})
        email_session, hotmail = acquire_email_session(config, mailtm, azpop, tmail)
        email = email_session.address
        log.info("[protocol] email=%s provider=%s", email, email_session.provider)

        log.info("[protocol] send_email_code…")
        backend.send_email_code(email, SIGNUP_URL)

        mail_api = MailApiClient(config)
        timeout_otp = int(config.get("timeout_otp") or 120)
        since_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 30))
        log.info("[protocol] polling OTP (timeout=%ss)…", timeout_otp)
        otp = wait_otp_smart(
            email_session,
            mail_api,
            mailtm,
            hotmail,
            timeout_otp,
            ignore_ids=set(),
            since_iso=since_iso,
            azpop=azpop,
            tmail_wibu=tmail,
        )
        if not otp:
            status = "error:protocol_otp_timeout"
            save_account(save_path, email, password, status)
            return ProtocolResult(False, status, email, password, duration_sec=time.time() - t0)

        log.info("[protocol] OTP=%s — verify…", otp)
        backend.verify_email_code(email, otp, SIGNUP_URL)

        log.info("[protocol] solve Turnstile…")
        token = _solve_turnstile(config, site_key=params.site_key, url=SIGNUP_URL)

        payload = build_signup_payload(
            email=email,
            password=password,
            given_name=first,
            family_name=last,
            email_validation_code=otp,
            turnstile_token=token,
        )
        log.info("[protocol] submit_signup…")
        response = backend.submit_signup(payload, SIGNUP_URL, token)
        result = backend.extract_sso(response)
        sso = (result.sso or "").strip() or read_sso_cookie_from_session(session)
        if not sso:
            status = "error:protocol_no_sso"
            save_account(save_path, email, password, status)
            return ProtocolResult(
                False,
                status,
                email,
                password,
                duration_sec=time.time() - t0,
                detail=f"http={getattr(response, 'status_code', '?')}",
            )

        duration = time.time() - t0
        log.info(
            "[protocol] SUCCESS email=%s sso_len=%s duration=%.1fs",
            email,
            len(sso),
            duration,
        )

        status = "success"
        sub = config.get("sub2api") or {}
        if sub.get("enabled", True) is not False:
            try:
                from grokreg.delivery.sub2api_oauth import add_grok_to_sub2api

                s2 = asyncio.run(
                    add_grok_to_sub2api(
                        None,
                        None,
                        config,
                        email,
                        password,
                        sso_cookie=sso,
                    )
                )
                if s2 and getattr(s2, "ok", False):
                    status = f"added_sub2api:{s2.name}"
                    log.info("[protocol] Sub2API OK name=%s", s2.name)
                elif s2:
                    status = (
                        f"success_sub2api_fail:"
                        f"{getattr(s2, 'stage', '?')}:"
                        f"{str(getattr(s2, 'message', ''))[:80]}"
                    )
                else:
                    status = "success_sub2api_fail:unknown"
            except Exception as e:
                log.exception("[protocol] Sub2API error: %s", e)
                status = f"success_sub2api_fail:{str(e)[:80]}"

        save_account(save_path, email, password, status)
        if hotmail:
            try:
                hotmail.mark_used(email_session)
            except Exception as e:
                log.warning("[protocol] hotmail mark_used: %s", e)
        return ProtocolResult(
            True,
            status,
            email,
            password,
            sso=sso,
            duration_sec=duration,
            detail="protocol",
        )

    except ProtocolEnvironmentError as e:
        email = email_session.address if email_session else ""
        status = f"error:protocol_env:{e.reason}:{str(e)[:80]}"
        log.error("[protocol] environment: %s", e)
        if email:
            save_account(save_path, email, password, status)
        return ProtocolResult(
            False, status, email, password, duration_sec=time.time() - t0, detail=str(e)
        )
    except Exception as e:
        email = email_session.address if email_session else ""
        status = f"error:protocol:{str(e)[:100]}"
        log.exception("[protocol] fatal: %s", e)
        if email:
            save_account(save_path, email, password, status)
        return ProtocolResult(
            False, status, email, password, duration_sec=time.time() - t0, detail=str(e)
        )
