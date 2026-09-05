"""Nhận ưu đãi acc mới sau khi Passport register xong.

Ưu đãi CapCut đang có (chính thức, 2026):
  1) Pro trial 7 ngày — web/app/desktop, vùng hỗ trợ, acc chưa từng Pro
  2) Invite PC — mời bạn mới cài CapCut PC, +7 ngày/người, tối đa 10 (70 ngày)
     người được mời cũng được 7 ngày, redeem trong 3 ngày sau khi cài PC
  3) Desktop campaign /u/e30 — đôi khi 30 ngày Pro (đăng nhập app PC)
  4) Commerce Pro trial — gói business riêng, không phải Pro thường
  5) Coupon / landing 7 ngày + % giảm — chỉ khi mở link subscribe
  6) VIP redeem — /commerce/vip-redeem (code đổi quà)

Trial 7 ngày thường cần session web + vùng IP. Module này login bằng sessionid
rồi gọi các endpoint công khai; không giả payment / không crack.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

from capreg.log import log
from capreg.paths import DATA

WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _cookie_map(sess: requests.Session) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for c in sess.cookies:
            if c.name and c.value:
                out[str(c.name)] = str(c.value)
    except Exception:
        pass
    return out


_EXCHANGE_URLS = [
    ("POST", "https://www.capcut.com/passport/web/login/"),
    ("POST", "https://www.capcut.com/passport/web/account/token/"),
    ("GET",  "https://www.capcut.com/passport/web/account/info/"),
]


def _exchange_session_key(session_key: str, proxy: str = "") -> tuple[str, requests.Session]:
    """
    Doi session_key (Passport mobile) -> sessionid web that.
    Tra ve (sessionid_string, requests.Session da co cookie).
    Neu that bai tra ve ("", session rong).
    """
    s = requests.Session()
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    s.headers.update({
        "User-Agent": WEB_UA,
        "Accept": "application/json, */*",
        "Origin": "https://www.capcut.com",
        "Referer": "https://www.capcut.com/",
        "Content-Type": "application/json",
    })

    for method, url in _EXCHANGE_URLS:
        try:
            payload = {"session_key": session_key, "mix_mode": 1}
            if method == "POST":
                r = s.post(url, json=payload, timeout=15, allow_redirects=True)
            else:
                r = s.get(url, params={"session_key": session_key}, timeout=15, allow_redirects=True)

            for c in r.cookies:
                if c.name and c.value:
                    try:
                        s.cookies.set(c.name, c.value, domain=".capcut.com")
                    except Exception:
                        pass

            sid = ""
            for c in s.cookies:
                if c.name and c.name.lower() in ("sessionid", "sessionid_ss", "sid_tt", "sid_guard"):
                    sid = c.value or ""
                    break

            if sid:
                log.info("[exchange] %s %s -> sessionid OK (len=%d)", method, url, len(sid))
                return sid, s

            try:
                body = r.json() if r.text else {}
                data = body.get("data") or {}
                sid = str(
                    data.get("sessionid")
                    or data.get("session_id")
                    or data.get("web_session")
                    or ""
                ).strip()
                if sid:
                    for domain in (".capcut.com", "www.capcut.com"):
                        try:
                            s.cookies.set("sessionid", sid, domain=domain)
                        except Exception:
                            pass
                    log.info("[exchange] %s %s -> sessionid from body OK", method, url)
                    return sid, s
            except Exception:
                pass

            log.debug("[exchange] %s %s HTTP %d -- no sessionid yet", method, url, r.status_code)

        except Exception as e:
            log.debug("[exchange] %s %s error: %s", method, url, e)

    log.warning("[exchange] tat ca endpoint that bai -- fallback session_key raw")
    return "", s


def _web_session(client, session_key: str, proxy: str = "") -> requests.Session:
    """
    Build web session voi sessionid that.
    Thu exchange session_key -> sessionid truoc;
    neu that bai fallback set session_key thang vao cookie.
    """
    sid, s = _exchange_session_key(session_key, proxy)

    if not sid:
        for name, val in _cookie_map(client.session).items():
            try:
                s.cookies.set(name, val, domain=".capcut.com")
            except Exception:
                pass
            if name.lower() in ("sessionid", "sessionid_ss", "sid_tt", "sid_guard"):
                sid = val or sid
        if not sid:
            sid = (session_key or "").strip()
        if sid:
            for domain in (".capcut.com", "www.capcut.com"):
                try:
                    s.cookies.set("sessionid", sid, domain=domain)
                except Exception:
                    pass

    s.headers.update({
        "User-Agent": WEB_UA,
        "Accept": "application/json, text/html, */*",
        "Origin": "https://www.capcut.com",
        "Referer": "https://www.capcut.com/activities/subscribe/",
    })
    return s


def _json(r: requests.Response) -> dict[str, Any]:
    try:
        j = r.json()
        return j if isinstance(j, dict) else {"raw": j, "http": r.status_code}
    except Exception:
        return {"http": r.status_code, "text": (r.text or "")[:240]}


def _looks_vip(blob: Any) -> str:
    text = json.dumps(blob, default=str).lower()
    if any(k in text for k in ("already_pro", "alreadypro", "is_vip\":true", '"vip":true')):
        return "already_pro"
    if any(k in text for k in ("free_trial", "freetrial", "trial_end", "trialing", "in_trial")):
        return "trial"
    if "7 day" in text or "7-day" in text or "7days" in text:
        return "trial_7d_page"
    if "30 day" in text or "30-day" in text:
        return "trial_30d_page"
    return ""


def claim_new_user_offers(
    client,
    config: dict[str, Any],
    *,
    session_key: str,
) -> dict[str, Any]:
    """Best-effort: login web bằng session_key rồi dò / nhận ưu đãi acc mới."""
    if config.get("claim_offer") is False:
        return {"ok": False, "skipped": True, "label": "off"}

    proxy = str(config.get("proxy") or "").strip()
    invite = str(config.get("invite_code") or config.get("offer_code") or "").strip()
    web = _web_session(client, session_key, proxy)
    hits: list[dict[str, Any]] = []
    labels: list[str] = []

    # 1) session web còn sống không
    try:
        r = web.get("https://www.capcut.com/passport/web/account/info/", timeout=20)
        info = _json(r)
        hits.append({"step": "account_info", "http": r.status_code, "body": info})
        logged = r.status_code < 400 and "session_expired" not in json.dumps(info)
        if logged:
            labels.append("web_login")
            log.info("[offer] web login OK")
        else:
            log.warning("[offer] web session hết / chưa bind: %s", str(info)[:160])
    except Exception as e:
        hits.append({"step": "account_info", "error": str(e)[:160]})
        logged = False

    # 2) trang subscribe — trial 7 ngày hiện ở đây nếu vùng + acc đủ điều kiện
    try:
        r = web.get("https://www.capcut.com/activities/subscribe/", timeout=20)
        kind = _looks_vip(r.text)
        hits.append({"step": "subscribe_page", "http": r.status_code, "hint": kind})
        if kind:
            labels.append(kind)
            log.info("[offer] subscribe page hint=%s", kind)
    except Exception as e:
        hits.append({"step": "subscribe_page", "error": str(e)[:160]})

    # 3) campaign desktop 30 ngày (trang công khai)
    try:
        r = web.get("https://www.capcut.com/u/e30", timeout=15, allow_redirects=True)
        kind = _looks_vip(r.text) or ("desktop30" if r.status_code < 400 else "")
        if r.status_code < 400:
            labels.append("desktop_e30")
        hits.append({"step": "desktop_e30", "http": r.status_code, "url": str(r.url)[:120]})
    except Exception as e:
        hits.append({"step": "desktop_e30", "error": str(e)[:160]})

    # 4) đổi code / invite
    if invite:
        for url, method, payload in (
            (
                "https://www.capcut.com/commerce/vip-redeem",
                "GET",
                {"code": invite},
            ),
            (
                "https://www.capcut.com/commerce/vip-redeem",
                "POST",
                {"code": invite},
            ),
        ):
            try:
                if method == "GET":
                    r = web.get(url, params=payload, timeout=15)
                else:
                    r = web.post(url, json=payload, timeout=15)
                body = _json(r)
                hits.append({"step": f"redeem_{method.lower()}", "http": r.status_code, "body": body})
                blob = json.dumps(body, default=str).lower()
                if r.status_code < 400 and "error" not in blob[:80]:
                    labels.append(f"redeem:{invite[:12]}")
                    log.info("[offer] redeem %s HTTP %s", method, r.status_code)
            except Exception as e:
                hits.append({"step": f"redeem_{method.lower()}", "error": str(e)[:160]})

    # 5) vài endpoint VIP/trial hay gặp — chỉ ghi nhận, không giả payment
    for url in (
        "https://www.capcut.com/passport/web/region/",
        "https://edit-api-sg.capcut.com/lv/v1/commerce/vip/user_vip_info",
        "https://commerce-api-sg.capcut.com/commerce/v1/subscription/info",
    ):
        try:
            r = web.get(url, timeout=12)
            body = _json(r)
            kind = _looks_vip(body)
            hits.append({"step": url.split(".com", 1)[-1][:60], "http": r.status_code, "hint": kind})
            if kind:
                labels.append(kind)
        except Exception as e:
            hits.append({"step": url, "error": str(e)[:120]})

    uniq = []
    for x in labels:
        if x not in uniq:
            uniq.append(x)
    label = "+".join(uniq) if uniq else "none"
    out = {
        "ok": bool(uniq),
        "label": label,
        "logged_in": logged,
        "invite": invite or None,
        "hits": hits,
    }
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "last_offer.json").write_text(
            json.dumps(out, ensure_ascii=False, default=str)[:8000],
            encoding="utf-8",
        )
    except Exception:
        pass
    log.info("[offer] kết quả=%s login=%s", label, logged)
    return out


# ---------------------------------------------------------------------------
# Active-offer checker  (gọi sau khi reg xong để lấy danh sách offer thực tế)
# ---------------------------------------------------------------------------

_OFFER_ENDPOINTS: list[tuple[str, str]] = [
    # (label_key, url)
    ("vip_info",       "https://edit-api-sg.capcut.com/lv/v1/commerce/vip/user_vip_info"),
    ("sub_info",       "https://commerce-api-sg.capcut.com/commerce/v1/subscription/info"),
    ("sub_list",       "https://commerce-api-sg.capcut.com/commerce/v1/subscription/list"),
    ("trial_center",   "https://www.capcut.com/commerce/trial-center"),
    ("benefit_center", "https://www.capcut.com/api/commerce/benefit/list"),
    ("region",         "https://www.capcut.com/passport/web/region/"),
]


def _ts_to_str(ts: Any) -> str:
    """Unix timestamp (ms hoặc s) → ISO string."""
    if not ts:
        return ""
    try:
        t = int(ts)
        if t > 1e12:          # milliseconds
            t //= 1000
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)


def _parse_vip_info(body: dict[str, Any]) -> dict[str, Any]:
    """Trích xuất thông tin Pro/trial từ response commerce endpoint."""
    result: dict[str, Any] = {
        "is_pro": False,
        "is_trial": False,
        "plan": "",
        "expire": "",
        "trial_days_left": None,
        "offers_available": [],
    }
    text = json.dumps(body, default=str).lower()

    # is_vip / is_pro flags
    data = body.get("data") or body
    if isinstance(data, dict):
        result["is_pro"] = bool(
            data.get("is_vip")
            or data.get("is_pro")
            or data.get("vip_status") == 1
            or data.get("subscription_status") in ("active", "trialing")
        )
        result["is_trial"] = bool(
            data.get("is_trial")
            or data.get("subscription_status") == "trialing"
            or "trial" in str(data.get("plan_name") or "").lower()
        )
        result["plan"] = str(
            data.get("plan_name")
            or data.get("product_name")
            or data.get("vip_level")
            or ""
        )
        # expiry
        for key in ("expire_time", "end_time", "trial_end_time", "current_period_end", "vip_end_time"):
            val = data.get(key)
            if val:
                result["expire"] = _ts_to_str(val)
                break
        # trial days left
        left = data.get("trial_days_remaining") or data.get("remaining_days")
        if left is not None:
            result["trial_days_left"] = int(left)
        # offers / benefits list
        for key in ("offers", "benefits", "available_offers", "items"):
            items = data.get(key)
            if isinstance(items, list) and items:
                result["offers_available"] = [
                    str(item.get("name") or item.get("title") or item.get("id") or item)[:80]
                    for item in items[:10]
                ]
                break

    # fallback: text scan
    if "trial" in text or "free_trial" in text:
        result["is_trial"] = True
    if any(k in text for k in ("is_vip\\\":true", '"vip":true', "already_pro")):
        result["is_pro"] = True

    return result


def check_active_offers(
    client,
    config: dict[str, Any],
    *,
    session_key: str,
) -> dict[str, Any]:
    """
    Sau khi reg xong, gọi hàng loạt endpoint để xác định offer nào đang có
    cho acc này. Trả về dict với:
        ok          — True nếu detect được ít nhất 1 offer
        summary     — string ngắn mô tả offer (ghi vào accounts.txt)
        is_pro      — bool
        is_trial    — bool
        plan        — tên gói (nếu có)
        expire      — thời gian hết hạn (nếu có)
        raw         — list các raw hit từng endpoint (debug)
    """
    proxy = str(config.get("proxy") or "").strip()
    web = _web_session(client, session_key, proxy)
    hits: list[dict[str, Any]] = []
    parsed_list: list[dict[str, Any]] = []
    labels: list[str] = []

    for label, url in _OFFER_ENDPOINTS:
        try:
            r = web.get(url, timeout=15, allow_redirects=True)
            body = _json(r)
            parsed = _parse_vip_info(body)
            hit = {
                "endpoint": label,
                "url": url,
                "http": r.status_code,
                "parsed": parsed,
            }
            hits.append(hit)
            parsed_list.append(parsed)

            if parsed["is_pro"]:
                tag = "pro_trial" if parsed["is_trial"] else "pro_active"
                labels.append(tag)
                if parsed["plan"]:
                    labels.append(f"plan:{parsed['plan'][:20]}")
                if parsed["expire"]:
                    labels.append(f"exp:{parsed['expire']}")
                log.info(
                    "[check_offer] %s → %s | plan=%s expire=%s",
                    label, tag, parsed["plan"], parsed["expire"],
                )
            elif parsed["is_trial"]:
                labels.append("trial_detected")
                log.info("[check_offer] %s → trial detected", label)
            elif parsed["offers_available"]:
                labels.append("offers:" + ",".join(parsed["offers_available"][:3]))
                log.info("[check_offer] %s → available offers: %s", label, parsed["offers_available"])
            else:
                vip_hint = _looks_vip(body)
                if vip_hint:
                    labels.append(vip_hint)
                log.debug("[check_offer] %s HTTP %s hint=%s", label, r.status_code, vip_hint or "none")

        except Exception as e:
            hits.append({"endpoint": label, "url": url, "error": str(e)[:120]})
            log.debug("[check_offer] %s error: %s", label, e)

    # deduplicate labels preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in labels:
        if x not in seen:
            seen.add(x)
            uniq.append(x)

    # aggregate parsed results
    is_pro    = any(p["is_pro"]    for p in parsed_list)
    is_trial  = any(p["is_trial"]  for p in parsed_list)
    plan      = next((p["plan"]    for p in parsed_list if p["plan"]),    "")
    expire    = next((p["expire"]  for p in parsed_list if p["expire"]),  "")
    avail     = next((p["offers_available"] for p in parsed_list if p["offers_available"]), [])
    days_left = next(
        (p.get("trial_days_left") for p in parsed_list if p.get("trial_days_left") is not None),
        None,
    )

    summary = "+".join(uniq) if uniq else "no_offer"
    out = {
        "ok":               bool(uniq),
        "summary":          summary,
        "is_pro":           is_pro,
        "is_trial":         is_trial,
        "plan":             plan,
        "expire":           expire,
        "trial_days_left":  days_left,
        "offers_available": avail,
        "raw":              hits,
    }

    # persist
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "last_offer_check.json").write_text(
            json.dumps(out, ensure_ascii=False, default=str, indent=2)[:16000],
            encoding="utf-8",
        )
    except Exception:
        pass

    log.info(
        "[check_offer] kết quả: %s | pro=%s trial=%s plan=%s expire=%s",
        summary, is_pro, is_trial, plan, expire,
    )
    return out
