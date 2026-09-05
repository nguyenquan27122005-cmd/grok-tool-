"""Redeem trial / promo Canva — /redeem/ → nhập mã → Dùng thử ngay.

Ưu tiên HTTP + cookie. Canva hay bắt login/JS thì fallback Chrome (pydoll).
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from canreg.log import log
from canreg.paths import DATA, GROK_ROOT, ROOT
from canreg.stop import StopRequested, raise_if_stop

FAIL_RE_BODY = re.compile(
    r"couldn.?t redeem|cannot redeem|can.?t redeem|unable to redeem|"
    r"invalid code|already (used|redeemed)|we couldn",
    re.I,
)

REDEEM_URL = "https://www.canva.com/redeem/"
LOGIN_URL = "https://www.canva.com/login/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

OK_HINTS = (
    "xin chúc mừng",
    "congratulations",
    "congratulation",
    "one day of luck",
    "trial activated",
    "trial has started",
    "you've got pro",
    "you have unlocked",
    "coupon applied",
    "coupon redeemed",
    "redeemed successfully",
    "you're now on",
    "you are now on",
    "started your trial",
    "đã kích hoạt",
    "dùng thử đã",
    "pro is now",
    "welcome to canva pro",
    "you're a pro",
    "you are a pro",
)
FAIL_HINTS = (
    "invalid code",
    "code is invalid",
    "expired",
    "already redeemed",
    "already used",
    "not eligible",
    "already have",
    "không hợp lệ",
    "hết hạn",
    "đã được sử dụng",
    "đã dùng",
    "unable to redeem",
    "can't redeem",
    "cannot redeem",
    "couldn't redeem",
    "couldn’t redeem",
    "we couldn’t redeem",
    "we couldn't redeem",
    "could not redeem",
)
CLICK_LABELS = (
    "dùng thử ngay",
    "claim trial",
    "claim my trial",
    "claim now",
    "start trial",
    "start your trial",
    "redeem my coupon",
    "redeem coupon",
    "redeem",
    "apply",
    "áp dụng",
    "xác nhận",
    "confirm",
    "continue",
    "tiếp tục",
    "get started",
    "bắt đầu",
)


@dataclass
class Acc:
    email: str = ""
    password: str = ""
    cookies: str = ""
    refresh: str = ""
    client_id: str = ""
    raw: str = ""
    # state hộp temp mail (tmail cookies/csrf) để lấy OTP login cho acc tmail
    extra: dict = field(default_factory=dict)


@dataclass
class RedeemResult:
    ok: bool
    status: str
    email: str
    code: str
    reason: str = ""
    ts: str = ""
    backend: str = ""
    url: str = ""
    proof: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        tag = "[+]" if self.ok else "[-]"
        st = "SUKSES" if self.ok else "FAIL"
        extra = self.reason or ("Redeem OK" if self.ok else "")
        return f"{tag} {st}: {self.email} | code={self.code} | {extra}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _jitter(a: float = 0.35, b: float = 1.1) -> None:
    time.sleep(random.uniform(a, b))


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def parse_codes(path: Path) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for ln in _read_lines(path):
        code = ln.split("|")[0].split()[0].strip()
        if code and code.upper() not in seen:
            seen.add(code.upper())
            codes.append(code)
    return codes


def parse_proxies(path: Path | None) -> list[str]:
    if not path:
        return []
    out: list[str] = []
    for ln in _read_lines(path):
        p = ln.strip()
        if p and "://" not in p and p.count(":") == 1:
            p = "http://" + p
        if p:
            out.append(p)
    return out


def _looks_cookie(blob: str) -> bool:
    s = (blob or "").strip()
    if not s:
        return False
    if s.startswith("{") or s.startswith("["):
        return True
    return "=" in s and ("c_user" in s or "session" in s.lower() or "C_AUTH" in s or "CAI" in s or "cookie" in s.lower() or s.count("=") >= 2)


def parse_account_line(raw: str) -> Acc | None:
    s = (raw or "").strip()
    if not s or s.startswith("#"):
        return None
    # cookie-only
    if _looks_cookie(s) and "@" not in s.split("|")[0]:
        return Acc(cookies=s, raw=s, email="(cookie)")
    parts = [p.strip() for p in s.split("|")]
    email = parts[0] if parts else ""
    if "@" not in email:
        return None
    acc = Acc(email=email, raw=s)
    if len(parts) > 1:
        acc.password = parts[1]
    # email|pass|refresh|client_id  hoặc  email|pass|cookie
    if len(parts) > 2:
        third = parts[2]
        if third.startswith("M.") or len(third) > 80:
            acc.refresh = third
        elif _looks_cookie(third):
            acc.cookies = third
        else:
            acc.refresh = third
    if len(parts) > 3:
        acc.client_id = parts[3]
    return acc


def parse_accounts(path: Path, *, success_only: bool = False) -> list[Acc]:
    accs: list[Acc] = []
    seen: set[str] = set()
    for ln in _read_lines(path):
        if success_only:
            bits = ln.split("|")
            st = bits[2].strip().lower() if len(bits) > 2 else ""
            if st and not st.startswith("success"):
                continue
        acc = parse_account_line(ln)
        if not acc:
            continue
        key = (acc.email or acc.cookies[:40]).lower()
        if key in seen:
            # dòng sau (success) ghi đè
            accs = [a for a in accs if (a.email or a.cookies[:40]).lower() != key]
        seen.add(key)
        accs.append(acc)
    return accs


def _mailbox_key(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    local, _, domain = e.partition("@")
    if "+" in local:
        base, _, tag = local.rpartition("+")
        if base and tag.isdigit():
            return f"{base}@{domain}"
    return e


def attach_hotmail_tokens(acc: Acc) -> Acc:
    if acc.refresh:
        return acc
    email = acc.email.lower()
    mailbox = _mailbox_key(acc.email)
    for name in ("hotmails.txt", "hotmails_used.txt"):
        for base in (GROK_ROOT / "data", ROOT / "data", ROOT.parent / "grok_tool" / "data"):
            p = base / name
            if not p.exists():
                continue
            for ln in _read_lines(p):
                parts = [x.strip() for x in ln.split("|")]
                if not parts:
                    continue
                key = parts[0].lower()
                if key != email and key != mailbox:
                    continue
                if len(parts) > 2 and parts[2]:
                    acc.refresh = parts[2]
                if len(parts) > 3 and parts[3]:
                    acc.client_id = parts[3]
                if not acc.password and len(parts) > 1:
                    acc.password = parts[1]
                return acc
    return acc


def _http_session(proxy: str = ""):
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
            "User-Agent": UA,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Origin": "https://www.canva.com",
            "Referer": REDEEM_URL,
        }
    )
    return s


def _apply_cookies(s, blob: str) -> int:
    n = 0
    raw = (blob or "").strip()
    if not raw:
        return 0
    items: list[tuple[str, str]] = []
    if raw.startswith("{") or raw.startswith("["):
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if isinstance(data, dict):
            if "cookies" in data and isinstance(data["cookies"], list):
                data = data["cookies"]
            else:
                items = [(str(k), str(v)) for k, v in data.items() if v is not None]
        if isinstance(data, list):
            for c in data:
                if isinstance(c, dict) and c.get("name"):
                    items.append((str(c["name"]), str(c.get("value") or "")))
    else:
        chunk = raw.split("cookie:", 1)[-1] if raw.lower().startswith("cookie") else raw
        for part in chunk.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                items.append((k.strip(), v.strip()))
    for k, v in items:
        if not k:
            continue
        try:
            s.cookies.set(k, v, domain=".canva.com")
            n += 1
        except Exception:
            pass
    return n


def _classify_text(text: str) -> str:
    low = (text or "").lower()
    if any(h in low for h in OK_HINTS):
        return "ok"
    if any(h in low for h in FAIL_HINTS):
        return "fail"
    return ""


def try_http_redeem(acc: Acc, code: str, proxy: str = "") -> RedeemResult | None:
    """Thử redeem HTTP khi có cookie. None = phải dùng Chrome."""
    if not acc.cookies:
        return None
    s = _http_session(proxy)
    n = _apply_cookies(s, acc.cookies)
    if n <= 0:
        return None
    try:
        r = s.get(REDEEM_URL, timeout=25)
    except Exception as e:
        log.info("HTTP redeem GET fail: %s", e)
        return None
    body = r.text or ""
    if "log in" in body.lower() and "redeem" in (r.url or "").lower() and "continue with email" in body.lower():
        return None
    csrf = ""
    for key in ("csrf", "Csrf-Token", "X-CSRF-Token", "csrfToken"):
        if key in r.headers:
            csrf = r.headers[key]
            break
    payloads = [
        {"code": code},
        {"couponCode": code},
        {"coupon_code": code},
        {"promoCode": code},
    ]
    paths = (
        "/_ajax/redeem",
        "/_ajax/coupon/redeem",
        "/rest/redeem",
        "/api/redeem",
    )
    headers = {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    for path in paths:
        for body_json in payloads:
            try:
                pr = s.post("https://www.canva.com" + path, json=body_json, headers=headers, timeout=25)
            except Exception:
                continue
            blob = f"{pr.status_code} {pr.text or ''}"[:1500]
            kind = _classify_text(blob)
            if pr.status_code < 400 and kind == "ok":
                return RedeemResult(
                    True,
                    "SUKSES",
                    acc.email,
                    code,
                    "Redeem OK – HTTP",
                    _now(),
                    "http",
                    str(pr.url or REDEEM_URL),
                    {"http": pr.status_code, "body": (pr.text or "")[:400]},
                )
            if kind == "fail" or pr.status_code in (400, 403, 409, 422):
                return RedeemResult(
                    False,
                    "FAIL",
                    acc.email,
                    code,
                    f"HTTP {pr.status_code}: {(pr.text or '')[:160]}",
                    _now(),
                    "http",
                    str(getattr(pr, "url", "") or ""),
                )
    return None


FILL_PROMO_JS = r"""
(() => {
  const val = %VAL%;
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 8 && r.height > 8 && !el.disabled && el.type !== 'hidden';
  };
  const setNative = (el, v) => {
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    const prev = el.value;
    el.focus();
    try { el.select(); } catch (e) {}
    if (desc && desc.set) desc.set.call(el, v); else el.value = v;
    if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };
  const inputs = [...document.querySelectorAll('input, textarea')].filter(vis);
  const el = inputs.find(i => /code|coupon|promo|redeem/i.test(
    i.name + i.id + i.placeholder + (i.getAttribute('aria-label') || '') + (i.autocomplete || '')
  )) || inputs.find(i => i.type === 'text' || i.type === 'search' || !i.type) || inputs[0];
  if (!el) return JSON.stringify({ok:0, n: inputs.length});
  setNative(el, val);
  return JSON.stringify({ok: el.value === val ? 1 : 0, val: el.value, ph: el.placeholder || ''});
})()
"""

CLICK_REDEEM_JS = r"""
(() => {
  const wants = %WANTS%;
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 8 && r.height > 8 && !el.disabled;
  };
  const label = (el) => (el.innerText || el.textContent || el.value || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const deny = /google|facebook|apple|privacy|terms|log in$|sign up with|continue with/;
  const nodes = [...document.querySelectorAll('button, [type=submit], [role=button], a')].filter(vis);
  for (const want of wants) {
    const hit = nodes.find(el => {
      const t = label(el);
      if (!t || t.length > 64 || deny.test(t)) return false;
      return t === want || t.includes(want);
    });
    if (hit) { hit.click(); return label(hit).slice(0, 48); }
  }
  return '';
})()
"""


async def _inject_cookies(tab: Any, blob: str) -> int:
    from canreg.browser import _js

    raw = (blob or "").strip()
    if not raw:
        return 0
    pairs: list[dict[str, str]] = []
    if raw.startswith("{") or raw.startswith("["):
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if isinstance(data, list):
            for c in data:
                if isinstance(c, dict) and c.get("name"):
                    pairs.append({"name": str(c["name"]), "value": str(c.get("value") or "")})
        elif isinstance(data, dict):
            src = data.get("cookies") if isinstance(data.get("cookies"), list) else None
            if src:
                for c in src:
                    if isinstance(c, dict) and c.get("name"):
                        pairs.append({"name": str(c["name"]), "value": str(c.get("value") or "")})
            else:
                for k, v in data.items():
                    if k != "cookies" and v is not None:
                        pairs.append({"name": str(k), "value": str(v)})
    else:
        chunk = raw.split("cookie:", 1)[-1] if raw.lower().startswith("cookie") else raw
        for part in chunk.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                pairs.append({"name": k.strip(), "value": v.strip()})
    n = 0
    for c in pairs:
        if not c["name"]:
            continue
        js = (
            "document.cookie = %s + '=;domain=.canva.com;path=/';"
            "document.cookie = %s;"
        )
        name = json.dumps(c["name"])
        full = json.dumps(f"{c['name']}={c['value']}; domain=.canva.com; path=/")
        await _js(tab, js % (name, full))
        n += 1
    return n


def _tmail_known_codes(acc: Acc, config: dict[str, Any]) -> set[str]:
    """Mã 6 số đang nằm trong hộp tmail (trước khi yêu cầu mã mới) — dùng làm
    ignore-list để không nhặt mã reg cũ/mã của lần login khác."""
    out: set[str] = set()
    try:
        from grokreg.mail.tmail_wibu import TmailWibuProvider

        tmail = TmailWibuProvider(dict(config.get("tmail_wibu") or {}))
        extra = dict(getattr(acc, "extra", None) or {})
        msgs, html_blob = tmail._fetch_messages(acc.email, extra)
        blob = " ".join(
            f"{m.get('subject') or ''} {m.get('from') or ''} {tmail._msg_blob(m)}"
            for m in msgs or []
        )
        out = set(re.findall(r"\b(\d{6})\b", f"{blob} {html_blob[:4000]}"))
        log.info("Tmail known codes (%s): %s", acc.email, sorted(out))
    except Exception as e:
        log.info("Tmail known codes lỗi (bỏ qua): %s", e)
    return out


def _login_mail(
    acc: Acc, config: dict[str, Any], ignore: set[str] | None = None
) -> dict[str, str]:
    from canreg.mail import wait_canva_mail

    # Acc tmail (reg bằng temp mail) không có refresh token — OTP login phải
    # lấy từ chính hộp tmail lúc reg qua session state trong acc.extra.
    xtra = dict(getattr(acc, "extra", None) or {})
    domain = acc.email.split("@")[-1].lower() if "@" in acc.email else ""
    is_tmail = bool(xtra.get("cookies")) or domain.endswith(".name.ng")

    class _Sess:
        provider = "tmail_wibu" if is_tmail else "hotmail"
        address = acc.email
        refresh_token = acc.refresh
        client_id = acc.client_id
        extra = xtra or {"mailbox": acc.email}

    kwargs: dict[str, Any] = {}
    if is_tmail:
        from grokreg.mail.tmail_wibu import TmailWibuProvider

        kwargs["tmail"] = TmailWibuProvider(dict(config.get("tmail_wibu") or {}))

    return wait_canva_mail(
        _Sess(),
        config,
        timeout=int(config.get("timeout_otp") or 180),
        since=time.time() - 3,
        require_login_subject=True,
        ignore_codes=set(ignore or ()),
        **kwargs,
    )


async def _login_browser(tab: Any, acc: Acc, config: dict[str, Any]) -> str:
    from canreg.browser import (
        _body,
        _click,
        _click_continue,
        _click_resend,
        _fill,
        _fill_otp,
        _js,
        _logged_in,
        _press_enter,
        _sleep,
        _stage,
        _wait_stage,
    )

    await tab.go_to(LOGIN_URL)
    await _sleep(2.2)
    url = str(await _js(tab, "location.href") or "")
    body = await _body(tab)
    if _logged_in(url, body):
        return "already"
    clicked = await _click(tab, "continue with email", "log in with email", "use email")
    if clicked:
        await _wait_stage(tab, not_in=("landing",), seconds=8)
    await _fill(tab, "email", acc.email)
    await _sleep(0.35)
    await _click_continue(tab)
    await _press_enter(tab)
    stage = await _wait_stage(tab, not_in=("email", "landing"), seconds=12)
    if stage == "otp":
        # tmail acc không có refresh nhưng vẫn lấy được OTP qua hộp tmail
        # (acc.extra); chỉ hotmail thiếu refresh mới bó tay.
        _extra = dict(getattr(acc, "extra", None) or {})
        _dom = acc.email.split("@")[-1].lower() if "@" in acc.email else ""
        _tmail_ok = bool(_extra.get("cookies")) or _dom.endswith(".name.ng")
        if not acc.refresh and not _tmail_ok:
            return "need_otp"
        # Mã OTP login bị ràng buộc vào phiên browser hiện tại và Canva vô
        # hiệu mã khi có mã mới/gõ sai: bấm Resend để lấy mã mới cho đúng
        # phiên, đồng thời đưa mã cũ trong hộp vào ignore-list.
        pre_codes: set[str] = set()
        if not acc.refresh:
            pre_codes = await asyncio.to_thread(_tmail_known_codes, acc, config)
            await _click_resend(tab)
        proof = await asyncio.to_thread(_login_mail, acc, config, pre_codes) or {}
        code = str(proof.get("code") or "")
        if not code:
            return "otp_timeout"
        await _fill_otp(tab, code)
        # Sau OTP Canva hay rẽ sang trang trung gian đã login (onboarding,
        # trang offer Pro…) mà không có marker "sign out"/"create a design".
        # Poll ~20s: coi là logged-in khi đã rời mọi màn hình auth (OTP,
        # login form) và đang ở canva.com thường — sai số thấp hơn việc
        # trông chờ một marker cụ thể trên landing động.
        _deadline = time.time() + 20
        ok = False
        url = ""
        body = ""
        while time.time() < _deadline:
            nxt = await _wait_stage(tab, not_in=("otp",), seconds=4)
            url = str(await _js(tab, "location.href") or "")
            body = await _body(tab)
            low = (body or "").lower()
            still_auth = (
                "signup" in url.lower()
                or "/login" in url.lower()
                or any(
                    x in low
                    for x in (
                        "enter the code",
                        "code we sent",
                        "we just sent",
                        "log in or sign up",
                        "continue with email",
                        "verification code",
                        "incorrect code",
                        "too many",
                    )
                )
            )
            if (
                nxt == "home"
                or _logged_in(url, body)
                or "sign out" in low
                or ("canva.com" in url.lower() and not still_auth)
            ):
                ok = True
                break
            await _sleep(2.0)
        if not ok:
            log.info(
                "OTP reject dump url=%s body=%.220r", url, (body or "").replace("\n", " ")
            )
        return "ok" if ok else "otp_rejected"
    # mật khẩu (nếu Canva hỏi)
    body = await _body(tab)
    if acc.password and any(x in body.lower() for x in ("password", "mật khẩu")):
        raw = await _js(
            tab,
            FILL_PROMO_JS.replace("%VAL%", json.dumps(acc.password)),
        )
        log.info("Login password fill %s", raw)
        await _click_continue(tab)
        await _sleep(2.5)
    url = str(await _js(tab, "location.href") or "")
    body = await _body(tab)
    if _logged_in(url, body):
        return "ok"
    return "login_incomplete"


async def _shot(tab: Any, tag: str) -> str:
    DATA.mkdir(parents=True, exist_ok=True)
    dest = DATA / "redeem_shots"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{tag}_{int(time.time())}.png"
    for name in ("take_screenshot", "screenshot"):
        fn = getattr(tab, name, None)
        if not fn:
            continue
        try:
            # Trang xác nhận render nặng — CDP screenshot có thể treo tới
            # timeout 60s của pydoll và chặn cả vòng (thậm chí gây retry oan).
            await asyncio.wait_for(fn(str(path)), timeout=6.0)
            return str(path)
        except TypeError:
            try:
                await asyncio.wait_for(fn(path=str(path)), timeout=6.0)
                return str(path)
            except Exception:
                pass
        except Exception:
            pass
    try:
        from canreg.browser import _js

        b64 = await _js(
            tab,
            """
(() => {
  return '';
})()
""",
        )
        del b64
    except Exception:
        pass
    return ""


async def redeem_browser(config: dict[str, Any], acc: Acc, code: str) -> RedeemResult:
    from canreg.browser import (
        _body,
        _js,
        _logged_in,
        _sleep,
        close_browser,
        open_browser,
    )

    browser = None
    try:
        raise_if_stop()
        browser, tab = await open_browser(config, wipe_old=False)
        if acc.cookies:
            await tab.go_to("https://www.canva.com/")
            await _sleep(1.0)
            n = 0
            data = None
            if str(acc.cookies).startswith(("{", "[")):
                try:
                    data = json.loads(acc.cookies)
                except ValueError:
                    data = None
            if isinstance(data, list) and data:
                # Cookie capture đầy đủ attr từ CDP → set qua CDP (chấp nhận
                # cả cookie httpOnly/__Host-, document.cookie không làm được).
                allowed = ("name", "value", "domain", "path", "secure",
                           "httpOnly", "sameSite", "expires")
                params = [
                    {k: c[k] for k in allowed if c.get(k) is not None}
                    for c in data
                    if isinstance(c, dict) and c.get("name") and c.get("value")
                ]
                if params:
                    try:
                        await tab.set_cookies(params)
                        n = len(params)
                    except Exception as e:
                        log.info("set_cookies CDP lỗi, fallback document.cookie: %s", e)
                        n = await _inject_cookies(tab, acc.cookies)
            else:
                n = await _inject_cookies(tab, acc.cookies)
            log.info("Cookie inject %s=%s", acc.email, n)
            await tab.go_to("https://www.canva.com/")
            await _sleep(1.6)
        url = str(await _js(tab, "location.href") or "")
        body = await _body(tab)
        if not _logged_in(url, body):
            how = await _login_browser(tab, acc, config)
            log.info("Login %s → %s", acc.email, how)
            if how not in ("ok", "already"):
                return RedeemResult(
                    False, "FAIL", acc.email, code, f"login:{how}", _now(), "browser"
                )
        await _sleep(random.uniform(0.4, 1.0))
        await tab.go_to(REDEEM_URL)
        await _sleep(2.4)
        filled = await _js(tab, FILL_PROMO_JS.replace("%VAL%", json.dumps(code)))
        log.info("Redeem fill %s %s", acc.email, filled)
        await _sleep(random.uniform(0.35, 0.8))
        # Coupon (VD LINKEDINCANVA) có 2 chặng: "redeem my coupon" → trang
        # "Get 3 months of Canva Pro FREE" → phải bấm thêm "Claim trial".
        clicked: list[str] = []
        misses = 0
        for _ in range(6):
            hit = str(
                await _js(tab, CLICK_REDEEM_JS.replace("%WANTS%", json.dumps(list(CLICK_LABELS))))
                or ""
            )
            if hit:
                clicked.append(hit)
                log.info("Redeem click %s", hit)
                misses = 0
                await _sleep(random.uniform(1.6, 2.6))
            else:
                misses += 1
                if misses >= 3:
                    break
                await _sleep(1.5)
        await _sleep(1.4)
        # Chờ Canva xác nhận gói — confirm có thể render chậm vài giây.
        # Trang offer ("Get 3 months of Canva Pro FREE") render chậm hơn vòng
        # click đầu, nên trong lúc chờ phải tự bấm thêm nút Claim trial.
        CLAIM_ONLY = (
            "claim trial",
            "claim my trial",
            "claim now",
            "start trial",
            "start your trial",
            "dùng thử ngay",
        )
        claims = 0
        kind = ""
        _deadline = time.time() + 30
        body = ""
        while time.time() < _deadline:
            body = await _body(tab)
            kind = _classify_text(body)
            if kind:
                break
            low = (body or "").lower()
            if claims < 3 and any(
                w in low for w in ("claim trial", "claim my trial", "free 90-day trial", "get 3 months")
            ):
                hit = str(
                    await _js(tab, CLICK_REDEEM_JS.replace("%WANTS%", json.dumps(list(CLAIM_ONLY))))
                    or ""
                )
                if hit:
                    claims += 1
                    clicked.append(hit)
                    log.info("Redeem claim click %s", hit)
                    await _sleep(2.5)
            await _sleep(2.0)
        url = str(await _js(tab, "location.href") or "")
        body = await _body(tab)
        shot = await _shot(tab, acc.email.split("@")[0][:18])
        proof = {
            "clicks": clicked,
            "fill": filled,
            "shot": shot,
            "body": (body or "").replace("\n", " ")[:400],
        }
        if kind == "fail" or FAIL_RE_BODY.search(body or ""):
            return RedeemResult(
                False,
                "FAIL",
                acc.email,
                code,
                (body or "").replace("\n", " ")[:180],
                _now(),
                "browser",
                url,
                proof,
            )
        if kind == "ok":
            reason = "Redeem OK – trang xác nhận gói"
            return RedeemResult(True, "SUKSES", acc.email, code, reason, _now(), "browser", url, proof)
        if not clicked:
            return RedeemResult(False, "FAIL", acc.email, code, "không thấy ô mã / nút Redeem", _now(), "browser", url, proof)
        return RedeemResult(
            False,
            "FAIL",
            acc.email,
            code,
            "đã bấm Redeem nhưng Canva chưa xác nhận gói | " + (body or "").replace("\n", " ")[:160],
            _now(),
            "browser",
            url,
            proof,
        )
    except StopRequested:
        raise
    except Exception as e:
        log.exception("redeem browser: %s", e)
        return RedeemResult(False, "FAIL", acc.email, code, str(e)[:180], _now(), "browser")
    finally:
        await close_browser(browser, wipe_old=False)


# Mã ưu đãi chỉ áp khi CÒN thật: Canva từ chối (invalid/expired/already used)
# thì ghi nhớ lại — các acc reg sau bỏ qua luôn thay vì đốt thời gian login lại.
DEAD_PATH = DATA / "redeem_dead.json"
DEAD_CODE_RE = re.compile(
    r"invalid|expired|already (redeemed|used)|not eligible"
    r"|hết hạn|không hợp lệ|đã được sử dụng|đã dùng",
    re.I,
)


def _load_dead_codes() -> dict[str, str]:
    try:
        d = json.loads(DEAD_PATH.read_text(encoding="utf-8"))
        return {str(k).upper(): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except Exception:
        return {}


def code_is_dead(code: str) -> bool:
    return bool(code) and code.strip().upper() in _load_dead_codes()


def note_redeem_result(rr: "RedeemResult") -> None:
    """Lưu mã bị Canva từ chối (lỗi MÃ, không phải lỗi login/mạng) vào sổ đen."""
    if getattr(rr, "ok", True) or not getattr(rr, "code", ""):
        return
    blob = f"{getattr(rr, 'reason', '')} {getattr(rr, 'status', '')}"
    if not DEAD_CODE_RE.search(blob):
        return
    code = rr.code.strip().upper()
    d = _load_dead_codes()
    if code not in d:
        d[code] = f"{_now()} {re.sub(r'\s+', ' ', rr.reason)[:90]}"
        try:
            DEAD_PATH.write_text(
                json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            log.warning(
                "Ưu đãi %s hết/không hợp lệ — ghi %s, bỏ qua auto-redeem các acc sau",
                code,
                DEAD_PATH.name,
            )
        except Exception as e:
            log.warning("ghi %s: %s", DEAD_PATH.name, e)


def load_redeem_code(config: dict[str, Any] | None = None) -> str:
    cfg = config or {}
    block = cfg.get("redeem") if isinstance(cfg.get("redeem"), dict) else {}
    code = str(block.get("code") or cfg.get("redeem_code") or "").strip()
    if code:
        return "" if code_is_dead(code) else code
    for p in (DATA / "codes.txt", DATA / "codes_web.txt"):
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#"):
                c = s.split()[0]
                if code_is_dead(c):
                    log.info("Bỏ qua mã đã chết %s trong %s", c, p.name)
                    continue
                return c
    return ""


def redeem_one_now(
    config: dict[str, Any],
    *,
    email: str,
    password: str = "",
    session: Any = None,
    code: str = "",
    cookies: Any = None,
) -> RedeemResult:
    """Redeem 1 acc ngay sau khi reg xong."""
    acc = Acc(email=email, password=password)
    if session is not None:
        acc.refresh = str(getattr(session, "refresh_token", "") or "")
        acc.client_id = str(getattr(session, "client_id", "") or "")
        acc.raw = str(getattr(session, "raw_line", "") or "")
        acc.extra = dict(getattr(session, "extra", None) or {})
    if cookies:
        try:
            acc.cookies = json.dumps(cookies)
        except (TypeError, ValueError):
            pass
    code = (code or load_redeem_code(config)).strip()
    if not code:
        return RedeemResult(False, "FAIL", email, "", "thieu ma redeem", _now())
    r = _one(config, acc, code, str(config.get("proxy") or ""), 0)
    note_redeem_result(r)
    try:
        print(r.line(), flush=True)
    except UnicodeEncodeError:
        print(r.line().encode("ascii", "replace").decode(), flush=True)
    log.info("%s", r.line())
    save_results([r], DATA / "proof.json")
    return r


def _one(config: dict[str, Any], acc: Acc, code: str, proxy: str, idx: int) -> RedeemResult:
    cfg = dict(config)
    if proxy:
        cfg["proxy"] = proxy
    cfg["chrome_debug_port"] = int(config.get("chrome_debug_port") or 9844) + idx
    cfg["fresh_profile_per_account"] = True
    acc = attach_hotmail_tokens(acc)
    last: RedeemResult | None = None
    retries = max(1, int((config.get("redeem") or {}).get("retries") or config.get("redeem_retries") or 2))
    for attempt in range(1, retries + 1):
        raise_if_stop()
        try:
            http = try_http_redeem(acc, code, proxy)
            if http is not None:
                last = http
                if http.ok or "invalid" in (http.reason or "").lower() or "expired" in (http.reason or "").lower():
                    return http
            last = asyncio.run(redeem_browser(cfg, acc, code))
            if last.ok:
                return last
        except StopRequested:
            return RedeemResult(False, "FAIL", acc.email, code, "stopped", _now())
        except Exception as e:
            last = RedeemResult(False, "FAIL", acc.email, code, str(e)[:180], _now())
        if attempt < retries:
            time.sleep(random.uniform(1.5, 3.0))
    return last or RedeemResult(False, "FAIL", acc.email, code, "unknown", _now())


def _pair(accs: list[Acc], codes: list[str]) -> list[tuple[Acc, str]]:
    if not accs or not codes:
        return []
    if len(codes) == 1:
        return [(a, codes[0]) for a in accs]
    n = min(len(accs), len(codes))
    return list(zip(accs[:n], codes[:n]))


def save_results(rows: list[RedeemResult], output: Path) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = [asdict(r) for r in rows]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log_path = DATA / "redeem_proof.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        for rec in payload:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    txt = DATA / "redeem_success.txt"
    lines = []
    if txt.exists():
        lines = txt.read_text(encoding="utf-8").splitlines()
    for r in rows:
        lines.append("|".join([r.email, r.code, r.status, r.ts, r.reason.replace("|", "/")]))
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_redeem(
    config: dict[str, Any],
    *,
    accounts_path: Path,
    codes_path: Path,
    proxy_path: Path | None = None,
    threads: int = 3,
    output: Path | None = None,
    success_only: bool = False,
) -> list[RedeemResult]:
    accs = parse_accounts(accounts_path, success_only=success_only)
    codes = parse_codes(codes_path)
    proxies = parse_proxies(proxy_path)
    if not accs:
        raise RuntimeError(f"Không có acc trong {accounts_path}")
    if not codes:
        raise RuntimeError(f"Không có mã trong {codes_path}")
    pairs = _pair(accs, codes)
    threads = max(1, min(int(threads or 1), 8, len(pairs)))
    out = output or (DATA / "proof.json")
    log.info(
        "Redeem acc=%s code=%s pair=%s threads=%s out=%s",
        len(accs),
        len(codes),
        len(pairs),
        threads,
        out,
    )
    results: list[RedeemResult] = []
    if threads == 1:
        for i, (acc, code) in enumerate(pairs):
            raise_if_stop()
            proxy = proxies[i % len(proxies)] if proxies else str(config.get("proxy") or "")
            r = _one(config, acc, code, proxy, i)
            print(r.line(), flush=True)
            log.info(r.line())
            results.append(r)
    else:
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futs = {}
            for i, (acc, code) in enumerate(pairs):
                proxy = proxies[i % len(proxies)] if proxies else str(config.get("proxy") or "")
                futs[pool.submit(_one, config, acc, code, proxy, i)] = (acc, code)
            for fut in as_completed(futs):
                r = fut.result()
                print(r.line(), flush=True)
                log.info(r.line())
                results.append(r)
    save_results(results, out)
    ok = sum(1 for r in results if r.ok)
    log.info("Redeem xong %s/%s → %s", ok, len(results), out)
    return results
