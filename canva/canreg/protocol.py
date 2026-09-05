"""HTTP Canva — CSRF /_ajax/csrf3/signup rồi POST /_ajax/signup (EMAIL_OTP_CODE).

Signup Canva dùng protobuf-JSON + reCAPTCHA Enterprise. HTTP thuần hay ra 400
khi thiếu captcha — worker fallback Chrome.
"""

from __future__ import annotations

import json
from typing import Any

from canreg.config import resolve_display_name
from canreg.log import log
from canreg.paths import DATA

SIGNUP_URL = "https://www.canva.com/signup/"
CSRF_PATH = "/_ajax/csrf3/signup"
SIGNUP_PATH = "/_ajax/signup"
PREFIX = "')]}while(1);</x>//"


def _letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _strip_prefix(text: str) -> str:
    raw = text or ""
    if raw.startswith(PREFIX):
        return raw[len(PREFIX) :]
    idx = raw.find("{")
    return raw[idx:] if idx >= 0 else raw


def _parse_body(text: str) -> Any:
    raw = _strip_prefix(text).strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw[:400]}


def _session(config: dict[str, Any]):
    proxy = str(config.get("proxy") or "").strip()
    try:
        from curl_cffi import requests as creq

        s = creq.Session(impersonate="chrome131")
    except Exception:
        import requests as creq

        s = creq.Session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.canva.com",
            "Referer": SIGNUP_URL,
        }
    )
    return s


def _dump(step: str, payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_protocol.json").write_text(
        json.dumps({"step": step, **payload}, ensure_ascii=False, default=str)[:8000],
        encoding="utf-8",
    )


def fetch_csrf(s, config: dict[str, Any]) -> str:
    url = "https://www.canva.com" + CSRF_PATH
    r = s.get(url, timeout=25)
    body = _parse_body(r.text or "")
    token = ""
    if isinstance(body, dict):
        token = str(body.get("A") or body.get("token") or "")
    log.info("[protocol] csrf3 HTTP %s token_len=%s", r.status_code, len(token))
    _dump("csrf", {"http": r.status_code, "body": body, "token_len": len(token)})
    if r.status_code >= 400 or not token:
        raise RuntimeError(f"csrf fail http={r.status_code}")
    return token


def _signup_bodies(email: str, name: str, code: str = "") -> list[tuple[str, dict[str, Any]]]:
    otp: dict[str, Any] = {_letter(1): email}
    if code:
        otp[_letter(2)] = code
    letter = {
        _letter(2): "en-US",
        _letter(4): name,
        _letter(6): {_letter(30): otp},
    }
    named = {
        "locale": "en-US",
        "displayName": name,
        "credentials": {
            "type": "EMAIL_OTP_CODE",
            "email": email,
        },
    }
    if code:
        named["credentials"]["code"] = code
    return [("letter", letter), ("named", named)]


def _classify(http: int, body: Any) -> tuple[str, str]:
    blob = json.dumps(body, default=str).lower() if body is not None else ""
    if "ineligible" in blob or "disposable" in blob or "temporary" in blob:
        return "error:email_flagged", "Canva chặn temp/disposable mail"
    if "recaptcha" in blob or "captcha" in blob:
        return "error:need_captcha", "cần reCAPTCHA Enterprise"
    if "invalid_one_time" in blob or "invalid one time" in blob:
        return "error:bad_otp", "OTP sai"
    if "csrf" in blob:
        return "error:csrf", "CSRF invalid"
    if http == 400:
        return "error:protocol_bad_request", "signup 400 — thiếu captcha / schema"
    if http == 403:
        return "error:protocol_cf", "Cloudflare 403"
    if http >= 400:
        return f"error:protocol_{http}", blob[:160]
    return "ok", ""


def _looks_code_sent(http: int, body: Any) -> bool:
    if http >= 400:
        return False
    blob = json.dumps(body, default=str).lower() if body is not None else ""
    return any(
        x in blob
        for x in ("signup_code", "code_verification", "email_otp", "code_sent")
    )


def _looks_logged_in(s, body: Any) -> bool:
    names: list[str] = []
    try:
        names = [str(c.name).lower() for c in s.cookies]
    except Exception:
        pass
    if any(n in ("c_auth", "cid", "cauid") or n.startswith("c_auth") for n in names):
        return True
    blob = json.dumps(body, default=str).lower() if body is not None else ""
    return "signup_completed" in blob or '"loggedin":true' in blob


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail,
) -> dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    name = resolve_display_name(config)
    s = _session(config)
    log.info("[protocol] GET signup (no Chrome)")
    try:
        s.get(SIGNUP_URL, timeout=25)
    except Exception as e:
        log.debug("signup GET: %s", e)

    try:
        csrf = fetch_csrf(s, config)
    except Exception as e:
        return {"ok": False, "status": "error:protocol_csrf", "detail": str(e)[:180]}

    last_http = 0
    last_body: Any = {}
    last_kind = ""
    sent_ok = False
    for label, body in _signup_bodies(email, name):
        log.info("[protocol] POST signup %s %s", label, email)
        r = s.post(
            "https://www.canva.com" + SIGNUP_PATH,
            json=body,
            timeout=30,
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "X-Csrf-Token": csrf,
                "X-Canva-Request": "updatesignup",
                "X-Canva-Accept-Prefix": "no-prefix",
            },
        )
        parsed = _parse_body(r.text or "")
        last_http, last_body = r.status_code, parsed
        status, detail = _classify(r.status_code, parsed)
        last_kind = status
        _dump(
            "signup_" + label,
            {"http": r.status_code, "body": parsed, "status": status},
        )
        log.info("[protocol] signup %s HTTP %s %s", label, r.status_code, str(parsed)[:160])
        if status == "error:email_flagged":
            return {"ok": False, "status": status, "detail": detail, "resp": parsed}
        if r.status_code < 400 or _looks_code_sent(r.status_code, parsed):
            sent_ok = True
            break

    if not sent_ok:
        return {
            "ok": False,
            "status": last_kind or "error:protocol_send",
            "detail": str(last_body)[:180],
            "resp": last_body,
        }

    if _looks_logged_in(s, last_body):
        return {
            "ok": True,
            "status": "success_protocol",
            "session": {"email": email, "name": name, "via": "http"},
            "resp": last_body,
        }

    log.info("[protocol] chờ OTP Canva…")
    proof = wait_mail() or {}
    code = str(proof.get("code") or "").strip()
    if proof.get("link") and not code:
        try:
            r2 = s.get(proof["link"], timeout=30, allow_redirects=True)
            log.info("[protocol] magic link HTTP %s %s", r2.status_code, getattr(r2, "url", "")[:80])
            if r2.status_code < 400 and _looks_logged_in(s, _parse_body(r2.text or "")):
                return {
                    "ok": True,
                    "status": "success_protocol",
                    "session": {"email": email, "url": str(getattr(r2, "url", ""))},
                    "proof": proof,
                }
        except Exception as e:
            log.warning("[protocol] magic get: %s", e)
    if not code:
        return {
            "ok": False,
            "status": "error:otp_timeout",
            "detail": "không thấy mã Canva",
            "proof": proof,
        }

    try:
        csrf = fetch_csrf(s, config)
    except Exception as e:
        return {"ok": False, "status": "error:protocol_csrf", "detail": str(e)[:180]}

    for label, body in _signup_bodies(email, name, code):
        r = s.post(
            "https://www.canva.com" + SIGNUP_PATH,
            json=body,
            timeout=30,
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "X-Csrf-Token": csrf,
                "X-Canva-Request": "updatesignup",
                "X-Canva-Accept-Prefix": "no-prefix",
            },
        )
        parsed = _parse_body(r.text or "")
        status, detail = _classify(r.status_code, parsed)
        _dump("verify_" + label, {"http": r.status_code, "body": parsed, "status": status})
        log.info("[protocol] verify %s HTTP %s", label, r.status_code)
        if r.status_code < 400 or _looks_logged_in(s, parsed):
            offer: dict[str, Any] = {}
            try:
                from canreg.offers import check_canva_offer

                offer = check_canva_offer(s)
            except Exception as e:
                log.debug("offer: %s", e)
            return {
                "ok": True,
                "status": "success_protocol",
                "offer": offer,
                "session": {"email": email, "name": name, "via": "http"},
                "proof": proof,
                "resp": parsed,
            }
        if status.startswith("error:email") or status == "error:bad_otp":
            return {"ok": False, "status": status, "detail": detail, "resp": parsed}

    return {
        "ok": False,
        "status": "error:protocol_no_session",
        "detail": "OTP gửi rồi nhưng verify HTTP fail — dùng Chrome",
        "proof": proof,
    }
