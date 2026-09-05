"""HeyGen HTTP — same idea as Grok protocol: no Chrome window.

POST api2.heygen.com/v1/pacific/account/magic_link  + Turnstile
GET  auth.heygen.com/magic-web/<token>              follow cookies
"""

from __future__ import annotations

import json
from typing import Any

from heyreg.log import log
from heyreg.paths import DATA
from heyreg.turnstile import kick_solver, solve_token

API = "https://api2.heygen.com"
SIGNUP_URL = "https://auth.heygen.com/signup"


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
            "Origin": "https://auth.heygen.com",
            "Referer": SIGNUP_URL,
            "Accept": "application/json, text/plain, */*",
        }
    )
    return s


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail,
) -> dict[str, Any]:
    kick_solver(config)
    s = _session(config)
    log.info("[protocol] GET signup (no Chrome)")
    try:
        s.get(SIGNUP_URL, timeout=25)
    except Exception as e:
        log.debug("signup GET: %s", e)

    try:
        ts = solve_token(config)
    except Exception as e:
        return {
            "ok": False,
            "status": "error:protocol_need_turnstile",
            "detail": str(e)[:180],
        }

    def _send_magic(token: str):
        payload = {
            "email": email,
            "using_verification_code": False,
            "locale": "en",
            "turnstile_token": token,
            "redirect_path": "/home",
        }
        log.info("[protocol] POST magic_link %s", email)
        rr = s.post(
            f"{API}/v1/pacific/account/magic_link",
            json=payload,
            timeout=30,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        log.info("[protocol] magic_link HTTP %s %s", rr.status_code, (rr.text or "")[:180])
        return rr

    r = _send_magic(ts)
    body = (r.text or "")[:400]
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_protocol.json").write_text(
        json.dumps({"step": "magic_link", "status": r.status_code, "body": r.text[:2000]}, ensure_ascii=False),
        encoding="utf-8",
    )
    if r.status_code >= 400:
        low = (r.text or "").lower()
        if "spam" in low or "flagged" in low:
            return {"ok": False, "status": "error:email_flagged", "detail": body}
        return {"ok": False, "status": f"error:protocol_send_{r.status_code}", "detail": body}

    log.info("[protocol] cho mail magic-web…")
    proof = wait_mail() or {}
    if not (proof.get("link") or "").strip():
        # magic_link HTTP 200 = account đã tạo trên server — mail có thể bị filter.
        # Resend cho CÙNG email (token Turnstile mới) trước khi bỏ account.
        try:
            log.warning("[protocol] chưa thấy mail — resend magic link cho cùng email")
            ts2 = solve_token(config)
            rr = _send_magic(ts2)
            if rr.status_code < 400:
                proof = wait_mail() or {}
        except Exception as e:
            log.warning("resend magic_link fail: %s", e)
    link = (proof.get("link") or "").strip()
    if not link:
        return {"ok": False, "status": "error:protocol_otp_timeout", "detail": "khong thay magic link"}

    log.info("[protocol] GET magic-web %s", link[:90])
    try:
        r2 = s.get(link, timeout=30, allow_redirects=True)
    except Exception as e:
        return {"ok": False, "status": "error:protocol_magic_get", "detail": str(e)[:160]}
    final = str(getattr(r2, "url", "") or "")
    log.info("[protocol] magic-web HTTP %s final=%s", r2.status_code, final[:100])
    (DATA / "last_protocol.json").write_text(
        json.dumps(
            {
                "step": "magic_web",
                "status": r2.status_code,
                "url": final,
                "cookies": list(getattr(s, "cookies", {}) or []),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    def _cookie_names() -> list[str]:
        # cookies có thể là CookieJar (object .name) hoặc container tên (str) —
        #_chấp nhận cả hai để không bao giờ làm sập luồng verify.
        try:
            out: list[str] = []
            for c in s.cookies:
                name = getattr(c, "name", None)
                if not name:
                    name = c if isinstance(c, str) else ""
                if name:
                    out.append(str(name).lower())
            return out
        except Exception:
            return []

    def _has_session(cnames: list[str]) -> bool:
        return any(
            any(k in n for k in ("session", "access", "auth_token", "heygen_session"))
            for n in cnames
            if n not in ("__cf_bm", "cf_clearance")
        )

    cookies = list(_cookie_names())
    final_l = final.lower()
    still_magic = "magic-web" in final_l or "/magic/" in final_l
    session_cookie = _has_session(_cookie_names())

    if not session_cookie:
        # Trang magic-web là SPA: trình duyệt thật chạy JS để đổi token lấy
        # session qua POST /v1/pacific/account/magic_link/verify (thấy trong
        # bundle auth.heygen.com). requests không chạy JS — gọi thẳng API.
        try:
            from urllib.parse import parse_qs, urlparse

            q = parse_qs(urlparse(link).query or "")
            redirect_path = (q.get("r") or ["/home"])[0]
            token_part = link.split("magic-web/", 1)[-1].split("?", 1)[0]
            vr = s.post(
                f"{API}/v1/pacific/account/magic_link/verify",
                json={
                    "token": token_part,
                    "fingerprint": str(config.get("heygen_fingerprint") or "web"),
                    "redirect_path": redirect_path,
                },
                timeout=30,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            log.info(
                "[protocol] magic verify HTTP %s %s",
                vr.status_code,
                (vr.text or "")[:160],
            )
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / "last_verify.json").write_text(
                json.dumps(
                    {
                        "step": "magic_verify",
                        "status": vr.status_code,
                        "body": (vr.text or "")[:2000],
                        "cookies": [str(getattr(c, "name", c)) for c in s.cookies],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            session_cookie = _has_session(_cookie_names())
            if not session_cookie and vr.status_code < 400:
                try:
                    vj = vr.json() or {}
                    data = vj.get("data") if isinstance(vj.get("data"), dict) else {}
                    tok = str(data.get("access_token") or vj.get("access_token") or "")
                    if tok:
                        proof.setdefault("access_token", tok)
                        session_cookie = True
                except Exception:
                    pass
        except Exception as e:
            log.warning("magic verify fail: %s", e)
        cookies = list(_cookie_names())

    landed = (
        "app.heygen.com" in final_l
        or "/onboarding" in final_l
        or "/welcome" in final_l
        or final_l.rstrip("/").endswith("heygen.com/home")
    )
    # session_cookie sau verify là đủ — SPA route client-side, URL có thể vẫn magic-web
    ok = r2.status_code < 400 and (landed or session_cookie)
    if "spam" in (r2.text or "").lower() and r2.status_code >= 400:
        ok = False
    if not ok:
        return {
            "ok": False,
            "status": "error:protocol_no_session",
            "detail": f"http={r2.status_code} url={final[:80]}",
            "proof": proof,
        }
    # Reg xong → check ngay plan/credit (ưu đãi nếu có)
    offer: dict[str, Any] = {}
    try:
        from heyreg.offers import check_heygen_offer

        offer = check_heygen_offer(s, str(proof.get("access_token") or ""))
    except Exception as e:
        log.debug("offer: %s", e)
    return {
        "ok": True,
        "status": "success_protocol",
        "url": final,
        "offer": offer,
        "proof": proof,
        "session": {"url": final, "cookies": cookies},
    }
