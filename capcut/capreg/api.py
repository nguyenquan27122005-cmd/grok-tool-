"""ByteDance Passport HTTP — match working CapCut web register (wahdalo + official extras)."""

from __future__ import annotations

import hashlib
import json
import os
import random
import string
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from capreg.log import log

DEFAULT_APP_ID = "348188"
DEFAULT_BASE = "https://www.capcut.com"
# Wire value used by the known-working public tool. mix_mode=1 does NOT encode type.
DEFAULT_OTP_TYPE = "34"
ROW_LOGIN = "https://login-row.www.capcut.com"
TTP_LOGIN = "https://login.us.capcut.com"
WEB_SEND = "/passport/web/email/send_code/"
WEB_REGISTER = "/passport/web/email/register_verify_login/"
WEB_REGION = "/passport/web/region/"


def region_secret() -> str:
    """Khóa ký email-hash — đọc từ env CAPCUT_REGION_SECRET hoặc config.json
    (region_secret). Không hardcode trong source."""
    sec = os.environ.get("CAPCUT_REGION_SECRET", "").strip()
    if sec:
        return sec
    try:
        from capreg.config import load_config

        sec = str((load_config() or {}).get("region_secret") or "").strip()
    except Exception:
        sec = ""
    if sec:
        return sec
    log.warning(
        "Thiếu region_secret — set capcut/config.json region_secret hoặc env CAPCUT_REGION_SECRET"
    )
    return ""


def mix_encode(s: str) -> str:
    return "".join(f"{ord(c) ^ 5:02x}" for c in str(s))


def mix_params(data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    out = dict(data)
    used = 0
    for k in keys:
        if k in out and out[k] is not None and str(out[k]) != "":
            out[k] = mix_encode(str(out[k]))
            used = 1
    out["mix_mode"] = used
    out["fixed_mix_mode"] = used
    return out


def _email_hash(email: str) -> str:
    return hashlib.sha256(f"{email.strip().lower()}{region_secret()}".encode()).hexdigest()


def _rand_id() -> str:
    return str(random.randint(10**18, 10**19 - 1))


def _verify_fp() -> str:
    def blk(n: int) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=n))

    return f"verify_{blk(8)}_{blk(8)}_{blk(4)}_{blk(4)}_{blk(4)}_{blk(12)}"


def _rand_birthday() -> str:
    return f"{random.randint(1988, 2002)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def _cookie(session: requests.Session, name: str) -> str:
    for c in session.cookies:
        if c.name == name and c.value:
            return str(c.value)
    return ""


@dataclass
class PassportClient:
    app_id: str
    base_url: str
    device_id: str
    install_id: str
    openudid: str
    session: requests.Session
    verify_fp: str
    email_ticket: str = ""
    otp_type: str = DEFAULT_OTP_TYPE
    country_code: str = ""
    csrf: str = ""

    def headers(self) -> dict[str, str]:
        csrf = self.csrf or _cookie(self.session, "passport_csrf_token") or _cookie(
            self.session, "passport_csrf_token_default"
        )
        self.csrf = csrf
        h = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/javascript",
            "Origin": "https://www.capcut.com",
            "Referer": "https://www.capcut.com/signup",
        }
        if csrf:
            h["x-tt-passport-csrf-token"] = csrf
        if self.country_code:
            h["store-country-code"] = self.country_code.lower()
            h["store-country-code-src"] = "uid"
        h["appid"] = self.app_id
        return h

    def params(self) -> dict[str, str]:
        p: dict[str, str] = {
            "aid": self.app_id,
            "account_sdk_source": "web",
            "language": "en",
            "verifyFp": self.verify_fp,
            "check_region": "1",
        }
        ms = _cookie(self.session, "msToken")
        if ms:
            p["msToken"] = ms
        webid = _cookie(self.session, "_tea_web_id")
        if webid:
            p["webid"] = webid
        return p

    def _post(self, path: str, data: dict[str, Any], *, base: str | None = None) -> dict[str, Any]:
        host = (base or self.base_url).rstrip("/")
        r = self.session.post(
            f"{host}{path}",
            headers=self.headers(),
            params=self.params(),
            data=data,
            timeout=20,
        )
        csrf = _cookie(self.session, "passport_csrf_token") or _cookie(
            self.session, "passport_csrf_token_default"
        )
        if csrf:
            self.csrf = csrf
        try:
            return r.json() if r.text else {"http": r.status_code, "raw": ""}
        except ValueError:
            return {"http": r.status_code, "raw": (r.text or "")[:400]}

    def warmup(self) -> None:
        try:
            self.session.get("https://www.capcut.com/signup", timeout=15)
        except Exception as e:
            log.debug("signup warmup: %s", e)
        try:
            self.session.cookies.set("s_v_web_id", self.verify_fp, domain=".capcut.com", path="/")
        except Exception:
            pass

    def update_region_by_email(self, email: str) -> dict[str, Any]:
        """Lấy CSRF / country. Không đổi host — send+register luôn www như tool public."""
        payload = {"type": "2", "hashed_id": _email_hash(email)}
        last: dict[str, Any] = {}
        for host in (DEFAULT_BASE, ROW_LOGIN, TTP_LOGIN):
            try:
                last = self._post(WEB_REGION, payload, base=host)
            except Exception as e:
                log.debug("region %s: %s", host, e)
                continue
            data = last.get("data") if isinstance(last.get("data"), dict) else {}
            if str(last.get("message") or "").lower() != "success":
                continue
            cc = str(data.get("country_code") or "").strip()
            if cc:
                self.country_code = cc
            # Giữ www.capcut.com. login-row + IP VN đang trả error 7 dù OTP đúng.
            self.base_url = DEFAULT_BASE
            log.info(
                "[api] region country=%s keep_host=%s csrf=%s fp=%s",
                self.country_code or "—",
                urlparse(self.base_url).netloc,
                "yes" if self.csrf else "no",
                self.verify_fp[:18],
            )
            return last
        log.warning("[api] region lookup miss, keep host=%s", self.base_url)
        return last

    def send_email_otp(self, email: str, password: str = "") -> dict[str, Any]:
        self.update_region_by_email(email)
        typ = self.otp_type or DEFAULT_OTP_TYPE
        payload: dict[str, Any] = {"email": email, "type": typ, "check_region": "1"}
        if password:
            payload["password"] = password
        out = self._post(WEB_SEND, mix_params(payload, ["email", "password"]))
        data = out.get("data") if isinstance(out.get("data"), dict) else {}
        ticket = str(data.get("email_ticket") or data.get("ticket") or "").strip()
        if ticket:
            self.email_ticket = ticket
        log.info(
            "[api] send_code host=%s type=%s ticket=%s msg=%s",
            urlparse(self.base_url).netloc,
            typ,
            "yes" if ticket else "no",
            out.get("message"),
        )
        return out

    def _sessionid_cookie(self) -> str:
        for name in ("sessionid", "sessionid_ss", "sid_tt"):
            v = _cookie(self.session, name)
            if v:
                return v
        return ""

    def _is_ok(self, out: dict[str, Any]) -> bool:
        if str(out.get("message") or "").lower() == "success":
            return True
        data = out.get("data") if isinstance(out.get("data"), dict) else {}
        if data.get("session_key") or data.get("user_id") or data.get("user_id_str"):
            return True
        return bool(self._sessionid_cookie())

    def register_account(
        self,
        email: str,
        password: str,
        code: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra = extra or {}
        birthday = str(extra.get("birthday") or _rand_birthday())
        # Account region ≠ IP country. VN trên login-row đang dính 7; tool public dùng ID/US.
        region = str(extra.get("region") or "US").upper()
        invite = str(extra.get("invite_code") or "")
        typ = self.otp_type or DEFAULT_OTP_TYPE
        payload: dict[str, Any] = {
            "email": email,
            "password": password,
            "code": code,
            "type": typ,
            "birthday": birthday,
            "force_user_region": region,
            "biz_param": json.dumps({"invite_code": invite} if invite else {}, separators=(",", ":")),
            "check_region": "1",
        }
        # Tool public không gửi email_ticket. Gửi ticket + type=34 raw → error 10 expired.
        body = mix_params(payload, ["email", "password", "code"])
        log.info(
            "[api] register POST %s%s type=%s ticket=%s csrf=%s region=%s fp=%s",
            urlparse(self.base_url).netloc,
            WEB_REGISTER,
            typ,
            "yes" if self.email_ticket else "no",
            "yes" if self.csrf else "no",
            region,
            self.verify_fp[:18],
        )
        last = self._post(WEB_REGISTER, body)
        data = last.get("data") if isinstance(last.get("data"), dict) else {}
        if self._is_ok(last):
            if isinstance(data, dict) and not data.get("session_key"):
                sid = self._sessionid_cookie()
                if sid:
                    data["session_key"] = sid
                    last["data"] = data
            return last
        log.warning(
            "[api] register fail %s code=%s desc=%s",
            WEB_REGISTER,
            data.get("error_code"),
            str(data.get("description") or "")[:80],
        )
        return last


def new_client(config: dict[str, Any] | None = None) -> PassportClient:
    cfg = config or {}
    proxy = str(cfg.get("proxy") or "").strip()
    s = requests.Session()
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
        log.info("Passport proxy on")
    client = PassportClient(
        app_id=str(cfg.get("app_id") or DEFAULT_APP_ID),
        base_url=str(cfg.get("api_base") or DEFAULT_BASE).rstrip("/"),
        device_id=_rand_id(),
        install_id=_rand_id(),
        openudid=uuid.uuid4().hex,
        session=s,
        verify_fp=_verify_fp(),
        otp_type=str(cfg.get("otp_type") or DEFAULT_OTP_TYPE),
    )
    client.warmup()
    return client
