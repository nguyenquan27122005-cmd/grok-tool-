"""HTTP register — zip Passport flow + grok mail."""

from __future__ import annotations

import json
from typing import Any

from capreg.api import new_client
from capreg.log import log
from capreg.paths import DATA


def register_protocol(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    wait_otp,
) -> dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    cfg_web = dict(config)
    cfg_web.setdefault("app_id", "348188")
    cfg_web.setdefault("api_base", "https://www.capcut.com")
    cfg_web.setdefault("otp_type", "34")
    client = new_client(cfg_web)
    log.info("[protocol] web send_code %s aid=%s type=%s", email, client.app_id, client.otp_type)
    sent = client.send_email_otp(email, password)
    (DATA / "last_protocol.json").write_text(
        json.dumps(
            {
                "step": "send_code",
                "app_id": client.app_id,
                "type": client.otp_type,
                "ticket": bool(client.email_ticket),
                "resp": sent,
            },
            ensure_ascii=False,
            default=str,
        )[:4000],
        encoding="utf-8",
    )
    data = sent.get("data") if isinstance(sent.get("data"), dict) else {}
    if str(sent.get("message") or "").lower() != "success":
        log.warning(
            "[protocol] send_code fail code=%s desc=%s",
            data.get("error_code"),
            str(data.get("description") or "")[:80],
        )

    msg = str(sent.get("message") or "").lower()
    if msg != "success":
        data = sent.get("data") if isinstance(sent.get("data"), dict) else {}
        code = data.get("error_code")
        desc = str(data.get("description") or sent.get("raw") or "")[:160]
        cap = data.get("captcha")
        need_cap = bool(
            (isinstance(cap, str) and cap.strip())
            or (isinstance(cap, dict) and cap)
            or "arkose" in json.dumps(sent, default=str).lower()
        )
        if need_cap:
            return {"ok": False, "status": "error:need_captcha", "detail": desc or str(code)}
        if code in (1206, 1203):
            return {
                "ok": False,
                "status": "error:send_otp_rate_limit",
                "detail": desc or str(code),
            }
        if code == 1355:
            return {
                "ok": False,
                "status": "error:send_otp_bad_app_id",
                "detail": f"{code}:{desc}",
            }
        if code == 6:
            # Passport risk-control "try again later" — session/fingerprint/IP bị chấm điểm.
            # Session + email mới (fp mới) thường qua được — worker sẽ tự retry.
            return {
                "ok": False,
                "status": "error:send_otp_try_later",
                "detail": desc or "risk control — thử lại session/email mới",
            }
        return {
            "ok": False,
            "status": f"error:send_otp:{code or 'fail'}",
            "detail": desc or str(sent)[:180],
        }

    log.info("[protocol] chờ OTP…")
    otp = (wait_otp() or "").strip()
    if not otp:
        return {"ok": False, "status": "error:otp_timeout", "detail": "không thấy mã 6 số"}

    log.info(
        "[protocol] register otp=%s host=%s ticket=%s csrf=%s",
        otp,
        client.base_url,
        "yes" if client.email_ticket else "no",
        "yes" if client.csrf else "no",
    )
    extra: dict[str, Any] = {}
    invite = str(config.get("invite_code") or config.get("offer_code") or "").strip()
    if invite:
        extra["invite_code"] = invite
        extra["share_uid"] = str(config.get("share_uid") or "")
    reg = client.register_account(email, password, otp, extra=extra or None)
    (DATA / "last_protocol.json").write_text(
        json.dumps({"step": "register", "resp": reg}, ensure_ascii=False, default=str)[:4000],
        encoding="utf-8",
    )
    if not client._is_ok(reg):
        rdata = reg.get("data") if isinstance(reg.get("data"), dict) else {}
        rcode = rdata.get("error_code")
        rdesc = str(rdata.get("description") or "")[:120]
        if rcode in (7, 1206, 1203):
            status = "error:register_rate_limit"
        elif rcode == 6:
            # Passport generic "try again later" — risk / IP / tần suất, không phải OTP sai
            status = "error:register_try_later"
        else:
            status = f"error:register:{rcode or 'fail'}"
        return {"ok": False, "status": status, "detail": rdesc or str(reg)[:180], "resp": reg}

    data = reg.get("data") if isinstance(reg.get("data"), dict) else {}
    session_key = str(data.get("session_key") or data.get("session") or "")
    log.info("[protocol] OK session_key_len=%s", len(session_key))

    offer: dict[str, Any] = {}
    try:
        from capreg.offers import claim_new_user_offers

        offer = claim_new_user_offers(client, config, session_key=session_key)
        if offer.get("label") and offer.get("label") != "none":
            log.info("[protocol] ưu đãi claim: %s", offer.get("label"))
        else:
            log.warning("[protocol] chưa nhận ưu đãi (vùng IP / cần mở web Join Pro)")
    except Exception as e:
        log.warning("[protocol] claim offer: %s", e)
        offer = {"ok": False, "label": "error", "detail": str(e)[:160]}

    # --- auto check offer đang có cho acc vừa reg ---
    offer_check: dict[str, Any] = {}
    try:
        from capreg.offers import check_active_offers

        offer_check = check_active_offers(client, config, session_key=session_key)
        log.info(
            "[protocol] offer check: %s | pro=%s trial=%s plan=%s expire=%s",
            offer_check.get("summary"),
            offer_check.get("is_pro"),
            offer_check.get("is_trial"),
            offer_check.get("plan") or "—",
            offer_check.get("expire") or "—",
        )
    except Exception as e:
        log.warning("[protocol] check_active_offers: %s", e)
        offer_check = {"ok": False, "summary": f"error:{str(e)[:80]}"}

    # --- credit balance riêng của Dreamina (bật bằng config "check_credits") ---
    credits: dict[str, Any] = {}
    if config.get("check_credits"):
        try:
            from capreg.credits import fetch_total_credits

            credits = fetch_total_credits(client)
            log.info("[protocol] credit check: %s", credits.get("summary"))
        except Exception as e:  # noqa: BLE001
            log.warning("[protocol] fetch_total_credits: %s", e)
            credits = {"ok": False, "total": -1, "summary": f"error:{str(e)[:80]}"}

    # build status string — ưu tiên offer_check nếu detect được pro/trial.
    # Lưu ý: "no_offer" là truthy — trước đây nó đè mất hint eligible của bước
    # claim (trial_7d_page). Giờ: chưa có trial active + hint eligible → ghi
    # eligible:<hint> để ledger/sheet phản ánh đúng "đủ điều kiện, chưa kích hoạt".
    _oc = str(offer_check.get("summary") or "")
    if _oc in ("no_offer", "") and offer.get("label"):
        _oc = f"eligible:{offer.get('label')}"
    offer_summary = _oc or "none"
    status = "success_protocol"
    if offer_check.get("is_pro") or offer_check.get("is_trial"):
        bits = ["success_protocol"]
        if offer_check.get("is_trial"):
            bits.append("trial")
        elif offer_check.get("is_pro"):
            bits.append("pro")
        if offer_check.get("plan"):
            bits.append(offer_check["plan"][:20])
        if offer_check.get("expire"):
            bits.append(f"exp:{offer_check['expire']}")
        status = ":".join(bits)
    elif offer.get("ok") and offer.get("label") not in ("", "none", "off"):
        status = f"success_protocol:{offer.get('label')}"

    return {
        "ok": True,
        "status": status,
        "session_key": session_key,
        "offer": offer,
        "offer_check": offer_check,
        "credits": credits,
        "session": {
            "session_key": session_key,
            "user_id": data.get("user_id"),
            "offer_claim": offer.get("label"),
            "offer_check": offer_check.get("summary"),
            "credits_total": credits.get("total") if credits.get("ok") else None,
            "credit_summary": credits.get("summary") or "",
            "is_pro": offer_check.get("is_pro"),
            "is_trial": offer_check.get("is_trial"),
            "plan": offer_check.get("plan") or "",
            "expire": offer_check.get("expire") or "",
        },
        "resp": reg,
    }
