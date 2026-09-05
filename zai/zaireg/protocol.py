"""HTTP register — chat.z.ai /auths/signup → mail → verify → finish."""

from __future__ import annotations

import json
from typing import Any

import re
import time

from zaireg.api import new_client, random_username, signup_needs_captcha
from zaireg.log import log
from zaireg.paths import DATA

_RETRY_SEC = re.compile(r"(\d+)\s*秒")


def _retry_after(resp: dict[str, Any]) -> int:
    blob = json.dumps(resp, default=str)
    m = _RETRY_SEC.search(blob)
    if m:
        return max(3, min(90, int(m.group(1)) + 2))
    if int(resp.get("http") or 0) == 429:
        return 30
    return 0


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_verify,
    prefetched: dict[str, Any] | None = None,
    prefetch_next: bool = False,
    on_signup_ok=None,
) -> dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    client = new_client(config)
    br: dict[str, Any] = {"signup_ok": True} if prefetched else {}
    sent: dict[str, Any]
    cap = ""
    if prefetched:
        # Signup đã chạy xong trong thread prefetch (cùng session/IP) — vào
        # thẳng bước chờ OTP.
        sent = prefetched.get("resp") or {"http": 200, "prefetched": True}
        log.info("[protocol] dùng pre-signup từ stash — skip Chrome cho %s", email)
    else:
        client.username = client.username or random_username()
        # captcha luôn bật — mint trước, signup HTTP 1 lần (tránh 429 vì probe + submit)
        log.warning("[protocol] mint captcha rồi signup HTTP 1 lần")
        last_err = ""
        try:
            from zaireg.captcha import solve_and_signup

            for attempt in range(1, 3):
                try:
                    br = solve_and_signup(
                        config,
                        email=email,
                        password=password,
                        username=client.username,
                        submit=False,
                    )
                except Exception as e:
                    last_err = str(e)[:180]
                    br = {}
                    log.warning("[protocol] mint lan %s fail: %s", attempt, last_err)
                if br.get("token") or br.get("signup_ok"):
                    break
                if attempt < 2:
                    log.warning("[protocol] mint miss — thử Chrome lần 2")
        except Exception as e:
            last_err = str(e)[:180]
            log.warning("[protocol] mint captcha fail: %s", e)
            return {
                "ok": False,
                "status": "error:need_captcha",
                "detail": last_err,
                "resp": {},
            }
        cap = str(br.get("token") or "")
        if br.get("signup_ok"):
            sent = br.get("resp") or {"http": 200, "browser_signup": True}
            log.info("[protocol] signup OK trong Chrome")
        elif cap:
            log.warning(
                "[protocol] captcha Chrome xong nhưng signup in-page fail — "
                "không POST token sang session khác (Aliyun gắn cookie/IP)"
            )
            return {
                "ok": False,
                "status": "error:skip_captcha",
                "detail": "captcha token bound to Chrome session",
                "resp": br,
            }
        else:
            return {
                "ok": False,
                "status": "error:need_captcha",
                "detail": str(br.get("detail") or last_err or "mint rỗng")[:180],
                "resp": {},
            }
    if on_signup_ok:
        # Email đã bị "đốt" cho z.ai từ lúc signup OK — mark ledger NGAY để
        # prefetch acquire không dính trùng mailbox/alias đang dùng (429).
        try:
            on_signup_ok()
        except Exception as e:
            log.debug("on_signup_ok: %s", e)
    if prefetch_next:
        try:
            from zaireg.prefetch import kick

            kick(config)
            log.info("[protocol] kick prefetch acc kế (chạy nền trong lúc chờ OTP)")
        except Exception as e:
            log.debug("prefetch kick: %s", e)
    (DATA / "last_protocol.json").write_text(
        json.dumps(
            {
                "step": "signup_captcha",
                "resp": sent,
                "cap_len": len(cap),
                "browser_signup": bool(br.get("signup_ok")),
            },
            ensure_ascii=False,
            default=str,
        )[:4000],
        encoding="utf-8",
    )
    if signup_needs_captcha(sent) and not br.get("signup_ok"):
        return {
            "ok": False,
            "status": "error:need_captcha",
            "detail": str(sent.get("detail") or sent)[:180],
            "resp": sent,
        }
    http = sent.get("http")
    detail = str(sent.get("detail") or sent.get("message") or "")
    if http and int(http) >= 400:
        log.warning("[protocol] signup fail http=%s %s", http, detail[:80])
        return {
            "ok": False,
            "status": f"error:signup:{http}",
            "detail": detail[:180],
            "resp": sent,
        }

    log.info("[protocol] chờ mail verify…")
    token = (wait_verify() or "").strip()
    if not token:
        return {"ok": False, "status": "error:otp_timeout", "detail": "không thấy token/OTP Z.ai"}

    ver = client.verify_email(email, token)
    (DATA / "last_protocol.json").write_text(
        json.dumps({"step": "verify_email", "resp": ver}, ensure_ascii=False, default=str)[:4000],
        encoding="utf-8",
    )
    fin = client.finish_signup(email, password, token)
    (DATA / "last_protocol.json").write_text(
        json.dumps({"step": "finish_signup", "resp": fin}, ensure_ascii=False, default=str)[:4000],
        encoding="utf-8",
    )
    http_f = fin.get("http")
    if http_f and int(http_f) >= 400 and not fin.get("token") and not fin.get("id"):
        # một số bản OpenWebUI signup xong là đủ, finish có thể 404
        if ver.get("token") or ver.get("id") or (ver.get("http") or 0) < 400:
            log.info("[protocol] finish skip/fail nhưng verify có vẻ OK — tiếp tục check quota")
        else:
            return {
                "ok": False,
                "status": f"error:finish:{http_f}",
                "detail": str(fin.get("detail") or fin)[:180],
                "resp": fin,
            }

    offer: dict[str, Any] = {}
    try:
        from zaireg.offers import check_zai_quota

        offer = check_zai_quota(client)
        log.info(
            "[protocol] quota: %s tokens=%s plan=%s",
            offer.get("summary"),
            offer.get("tokens"),
            offer.get("plan") or "—",
        )
    except Exception as e:
        log.warning("[protocol] quota: %s", e)
        offer = {"ok": False, "summary": f"error:{str(e)[:80]}"}

    status = "success_protocol"
    if offer.get("tokens"):
        status = f"success_protocol:{offer.get('summary') or 'quota'}"
    elif offer.get("summary") and offer.get("summary") not in ("no_offer", "none"):
        status = f"success_protocol:{offer.get('summary')}"

    return {
        "ok": True,
        "status": status,
        "offer": offer,
        "session": {
            "email": email,
            "username": client.username,
            "summary": offer.get("summary"),
            "tokens": offer.get("tokens"),
            "plan": offer.get("plan") or "",
        },
        "resp": fin or ver or sent,
    }
