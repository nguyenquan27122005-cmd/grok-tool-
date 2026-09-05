"""HTTP probe / Azure AD B2C signup for Genspark.

Public surfaces (see SOURCES.md):
- https://www.genspark.ai/api/login → B2C `b2c_1_new_login` on login.genspark.ai
- Tenant gensparkad.onmicrosoft.com, client_id 536a4e98-fd24-4cbc-a67b-417e209e0080
- SelfAsserted: email + image CAPTCHA + 6-digit verify + password
- Redirect https://www.genspark.ai/api/auth?code=…

Signup almost always needs the B2C image CAPTCHA. Without a solver key this
module dumps `data/last_protocol.json` and yields `error:need_browser`.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from curl_cffi import requests  # TLS fingerprint = Chrome thật, không khai "Python"

from gsparkreg.captcha import solve_image
from gsparkreg.log import log
from gsparkreg.paths import DATA

HOME = "https://www.genspark.ai/"
LOGIN_API = "https://www.genspark.ai/api/login"
AUTH_API = "https://www.genspark.ai/api/auth"
IS_LOGIN = "https://www.genspark.ai/api/is_login"
USER_API = "https://www.genspark.ai/api/user"
B2C_HOST = "login.genspark.ai"
B2C_TENANT = "gensparkad.onmicrosoft.com"
B2C_POLICY = "b2c_1_new_login"
CLIENT_ID = "536a4e98-fd24-4cbc-a67b-417e209e0080"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SETTINGS_RE = re.compile(r"var\s+SETTINGS\s*=\s*(\{.*?\});\s*", re.S)
CAPTCHA_IMG_RE = re.compile(
    r'<img[^>]+src=["\'](data:image[^"\']+)["\']',
    re.I,
)
INPUT_RE = re.compile(
    r"<input[^>]+>",
    re.I,
)


def _dump(payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_protocol.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)[:20000],
        encoding="utf-8",
    )


def _session(config: dict[str, Any]) -> requests.Session:
    s = requests.Session(impersonate="chrome131")
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def _parse_settings(html: str) -> dict[str, Any]:
    m = SETTINGS_RE.search(html or "")
    if not m:
        return {}
    raw = m.group(1)
    try:
        return json.loads(raw)
    except Exception:
        try:
            import ast

            return ast.literal_eval(raw) if raw.startswith("{") else {}
        except Exception:
            return {}


def _csrf(sess: requests.Session, settings: dict[str, Any]) -> str:
    tok = str(settings.get("csrf") or "").strip()
    if tok:
        return tok
    for c in sess.cookies:
        if "csrf" in (c.name or "").lower():
            return c.value or ""
    return ""


def _selfasserted_url(page_url: str, settings: dict[str, Any]) -> str:
    api = str(settings.get("api") or "SelfAsserted").strip() or "SelfAsserted"
    trans = str(settings.get("transId") or settings.get("transid") or "").strip()
    parsed = urlparse(page_url)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rsplit('/', 1)[0]}/"
    # Typical: .../b2c_1_new_login/SelfAsserted?tx=StateProperties=...&p=B2C_1_new_login
    path = urljoin(base, api)
    policy = str(settings.get("hosts", {}).get("policy") or B2C_POLICY)
    q = []
    if trans:
        q.append(f"tx=StateProperties={trans}")
    q.append(f"p={policy}")
    return path + ("?" + "&".join(q) if q else "")


def _input_names(html: str) -> list[str]:
    names: list[str] = []
    for tag in INPUT_RE.findall(html or ""):
        m = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
        if m:
            names.append(m.group(1))
    return names


def _captcha_src(html: str) -> str:
    m = CAPTCHA_IMG_RE.search(html or "")
    if m:
        src = m.group(1)
        if "logo" not in src.lower():
            return src
    for m in re.finditer(r'(data:image/(?:png|jpeg|gif|bmp);base64,[A-Za-z0-9+/=]+)', html or ""):
        src = m.group(1)
        if "logo" not in src.lower() and len(src) > 80:
            return src
    return ""


def _post_selfasserted(
    sess: requests.Session,
    url: str,
    csrf: str,
    data: dict[str, str],
) -> requests.Response:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-TOKEN": csrf,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": f"https://{B2C_HOST}",
        "Referer": url.split("?")[0],
    }
    return sess.post(url, data=data, headers=headers, timeout=30, allow_redirects=False)


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_mail: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    s = _session(config)
    hits: list[dict[str, Any]] = []
    try:
        boot = s.get(HOME, timeout=25)
        hits.append({"url": HOME, "status": boot.status_code})
    except Exception as e:
        out = {"ok": False, "status": "error:home_get", "detail": str(e)[:200]}
        _dump(out)
        return out

    try:
        login = s.get(
            LOGIN_API,
            params={"redirect_url": "/"},
            timeout=30,
            allow_redirects=True,
        )
    except Exception as e:
        out = {"ok": False, "status": "error:login_get", "detail": str(e)[:200], "hits": hits}
        _dump(out)
        return out

    html = login.text or ""
    page_url = str(login.url or "")
    hits.append({"url": page_url, "status": login.status_code, "len": len(html)})
    settings = _parse_settings(html)
    csrf = _csrf(s, settings)
    names = _input_names(html)
    captcha_src = _captcha_src(html)
    trans = str(settings.get("transId") or "")[:80]
    log.info(
        "protocol B2C url=%s csrf=%s trans=%s captcha=%s inputs=%s",
        page_url[:90],
        bool(csrf),
        bool(trans),
        bool(captcha_src),
        names[:12],
    )

    if not csrf or not settings:
        out = {
            "ok": False,
            "status": "error:need_browser",
            "detail": "B2C SETTINGS/csrf không scrape được — dùng Chrome",
            "hits": hits,
            "page_url": page_url[:200],
        }
        _dump(out)
        return out

    if not captcha_src:
        # Login page — switch to unified signup (local=signup).
        parsed = urlparse(page_url)
        csrf_q = csrf
        trans_q = str(settings.get("transId") or "")
        signup_url = (
            f"{parsed.scheme}://{parsed.netloc}"
            f"{settings.get('hosts', {}).get('tenant') or '/gensparkad.onmicrosoft.com/B2C_1_new_login'}"
            f"/api/CombinedSigninAndSignup/unified?local=signup"
            f"&csrf_token={csrf_q}&tx={trans_q}&p={B2C_POLICY}"
        )
        try:
            su = s.get(signup_url, timeout=30, allow_redirects=True)
            html = su.text or ""
            page_url = str(su.url or page_url)
            hits.append({"url": page_url[:180], "status": su.status_code, "len": len(html)})
            settings = _parse_settings(html) or settings
            csrf = _csrf(s, settings) or csrf
            names = _input_names(html)
            captcha_src = _captcha_src(html)
            log.info("protocol signup unified captcha=%s inputs=%s", bool(captcha_src), names[:12])
        except Exception as e:
            log.warning("unified signup: %s", e)
        if not captcha_src:
            out = {
                "ok": False,
                "status": "error:need_browser",
                "detail": "Trang B2C login, chưa ra form signup+CAPTCHA — dùng Chrome",
                "hits": hits,
                "inputs": names,
                "page_url": page_url[:200],
            }
            _dump(out)
            return out

    try:
        answer = solve_image(captcha_src, config)
    except Exception as e:
        out = {
            "ok": False,
            "status": "error:need_captcha",
            "detail": str(e)[:220],
            "hits": hits,
        }
        _dump(out)
        return out

    sa_url = _selfasserted_url(page_url, settings)
    # Field names Azure B2C signup commonly uses; extra names from the page.
    email_key = next((n for n in names if "email" in n.lower() and "verif" not in n.lower()), "email")
    captcha_key = next(
        (n for n in names if "captcha" in n.lower() or "captchauserinput" in n.lower()),
        "captchaUserInput",
    )
    send_body = {
        "request_type": "VERIFICATION_REQUEST",
        email_key: email,
        captcha_key: answer,
    }
    try:
        sent = _post_selfasserted(s, sa_url, csrf, send_body)
    except Exception as e:
        out = {"ok": False, "status": "error:send_code", "detail": str(e)[:200], "hits": hits}
        _dump(out)
        return out
    hits.append({"url": sa_url, "status": sent.status_code, "body": (sent.text or "")[:400]})
    low = (sent.text or "").lower()
    if sent.status_code >= 400 or "error" in low and "captcha" in low:
        out = {
            "ok": False,
            "status": "error:captcha_failed" if "captcha" in low else "error:send_code",
            "detail": (sent.text or "")[:220],
            "hits": hits,
        }
        _dump(out)
        return out

    sent_at = time.time()
    mail = wait_mail(timeout=int(config.get("timeout_otp") or 180), after_ts=sent_at)
    code = str((mail or {}).get("code") or "").strip()
    if not code:
        out = {"ok": False, "status": "error:no_otp", "detail": "hết timeout không thấy mã Genspark", "hits": hits}
        _dump(out)
        return out

    verify_key = next((n for n in names if "verif" in n.lower() or n.lower() in ("otp", "code")), "emailVerificationCode")
    verify_body = {
        "request_type": "VERIFICATION_STATUS",
        email_key: email,
        verify_key: code,
    }
    try:
        ver = _post_selfasserted(s, sa_url, csrf, verify_body)
        hits.append({"url": "verify", "status": ver.status_code, "body": (ver.text or "")[:300]})
    except Exception as e:
        log.warning("verify post: %s", e)

    create_body = {
        email_key: email,
        "newPassword": password,
        "reenterPassword": password,
        "newPasswordRetype": password,
        verify_key: code,
    }
    try:
        created = _post_selfasserted(s, sa_url, csrf, create_body)
        hits.append({"url": "create", "status": created.status_code, "body": (created.text or "")[:400]})
    except Exception as e:
        out = {"ok": False, "status": "error:create", "detail": str(e)[:200], "hits": hits}
        _dump(out)
        return out

    # Confirmed → /api/auth
    confirmed = page_url
    for suffix in (
        "api/CombinedSigninAndSignup/confirmed",
        "api/SelfAsserted/confirmed",
    ):
        try:
            u = urljoin(page_url if page_url.endswith("/") else page_url + "/", suffix)
            r = s.get(u, timeout=25, allow_redirects=True)
            hits.append({"url": str(r.url)[:180], "status": r.status_code})
            confirmed = str(r.url or confirmed)
            if "genspark.ai" in confirmed and "login" not in confirmed:
                break
        except Exception as e:
            hits.append({"url": suffix, "error": str(e)[:120]})

    ok_login = False
    user: dict[str, Any] = {}
    try:
        chk = s.get(IS_LOGIN, timeout=15)
        ok_login = (chk.text or "").strip().lower() in ("true", "1", '{"ok":true}')
        hits.append({"url": IS_LOGIN, "status": chk.status_code, "body": (chk.text or "")[:80]})
        ur = s.get(USER_API, timeout=15)
        if ur.status_code < 400:
            try:
                user = ur.json() if ur.text else {}
            except Exception:
                user = {"raw": ur.text[:200]}
    except Exception as e:
        log.debug("is_login: %s", e)

    cookies = {c.name: c.value for c in s.cookies}
    session = {
        "email": email,
        "url": confirmed[:200],
        "cookie_keys": list(cookies.keys()),
        "session_id": cookies.get("session_id") or cookies.get("sessionId") or "",
        "user": user,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2)[:12000],
        encoding="utf-8",
    )
    ok = bool(ok_login or session.get("session_id") or (isinstance(user, dict) and user))
    out = {
        "ok": ok,
        "status": "success" if ok else "error:need_browser",
        "detail": confirmed[:180],
        "session": session,
        "hits": hits,
    }
    _dump({k: v for k, v in out.items() if k != "session"})
    return out
