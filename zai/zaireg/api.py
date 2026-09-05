"""chat.z.ai HTTP — from official frontend /api/v1/auths/*."""

from __future__ import annotations

import json
import random
import string
from dataclasses import dataclass, field
from typing import Any

import requests

from zaireg.log import log

BASE = "https://chat.z.ai"
API = f"{BASE}/api/v1"
FE_VER = "prod-fe-1.1.84"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def random_username() -> str:
    return "u" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


@dataclass
class ZaiClient:
    session: requests.Session
    username: str = ""
    token: str = ""
    last: dict[str, Any] = field(default_factory=dict)

    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": BASE,
            "Referer": f"{BASE}/auth?action=signup",
            "X-FE-Version": FE_VER,
        }

    def warmup(self) -> None:
        try:
            self.session.get(f"{BASE}/auth?action=signup", headers=self.headers(), timeout=20)
        except Exception as e:
            log.debug("warmup: %s", e)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = self.session.post(
            f"{API}{path}",
            headers=self.headers(),
            json=body,
            timeout=25,
        )
        try:
            out = r.json() if r.text else {"http": r.status_code}
        except ValueError:
            out = {"http": r.status_code, "raw": (r.text or "")[:400]}
        if not isinstance(out, dict):
            out = {"data": out, "http": r.status_code}
        out.setdefault("http", r.status_code)
        self.last = out
        return out

    def _get(self, path: str) -> dict[str, Any]:
        r = self.session.get(f"{API}{path}", headers=self.headers(), timeout=20)
        try:
            out = r.json() if r.text else {"http": r.status_code}
        except ValueError:
            out = {"http": r.status_code, "raw": (r.text or "")[:400]}
        if not isinstance(out, dict):
            out = {"data": out, "http": r.status_code}
        out.setdefault("http", r.status_code)
        return out

    def signup(self, email: str, password: str, username: str = "", captcha: str = "") -> dict[str, Any]:
        self.username = username or self.username or random_username()
        body: dict[str, Any] = {
            "name": self.username,
            "email": email,
            "password": password,
            "profile_image_url": "",
            "sso_redirect": "",
        }
        if captcha:
            body["captcha_verify_param"] = captcha
        log.info("[api] POST /auths/signup %s user=%s", email, self.username)
        return self._post("/auths/signup", body)

    def resend_email(self, email: str) -> dict[str, Any]:
        return self._post(
            "/auths/resend_email",
            {"name": self.username, "email": email, "sso_redirect": ""},
        )

    def verify_email(self, email: str, token: str) -> dict[str, Any]:
        self.token = token
        log.info("[api] POST /auths/verify_email token_len=%s", len(token))
        return self._post(
            "/auths/verify_email",
            {"username": self.username, "email": email, "token": token},
        )

    def finish_signup(self, email: str, password: str, token: str = "") -> dict[str, Any]:
        tok = token or self.token
        log.info("[api] POST /auths/finish_signup")
        return self._post(
            "/auths/finish_signup",
            {
                "username": self.username,
                "email": email,
                "token": tok,
                "password": password,
                "profile_image_url": "",
                "sso_redirect": "",
            },
        )

    def signin(self, email: str, password: str, captcha: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {"email": email, "password": password, "captcha_verify_param": captcha}
        return self._post("/auths/signin", body)

    def plan_usage(self) -> dict[str, Any]:
        return self._get("/users/user/plan-usage")

    def subscription(self) -> dict[str, Any]:
        return self._get("/users/user/subscription")


def signup_needs_captcha(out: dict[str, Any]) -> bool:
    blob = json.dumps(out, default=str).lower()
    return any(
        k in blob
        for k in (
            "captcha",
            "verification failed",
            "complete verification",
            "aliyun",
        )
    )


def new_client(config: dict[str, Any] | None = None) -> ZaiClient:
    cfg = config or {}
    s = requests.Session()
    proxy = str(cfg.get("proxy") or "").strip()
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
        log.info("Z.ai proxy on")
    client = ZaiClient(session=s)
    client.warmup()
    return client
