from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from canreg.config import resolve_display_name, resolve_password
from canreg.log import log
from canreg.mail import acquire_email, wait_canva_mail
from canreg.paths import ROOT
from canreg.stop import StopRequested, raise_if_stop


@dataclass
class Result:
    ok: bool
    status: str
    email: str = ""
    password: str = ""
    detail: str = ""
    duration_sec: float = 0.0


def _save(path: Path, email: str, password: str, status: str, extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = " ".join(str(extra or "").split())
    bits = [email, password, status, time.strftime("%Y-%m-%d %H:%M:%S")]
    if extra:
        bits.append(extra)
    with path.open("a", encoding="utf-8") as f:
        f.write("|".join(bits) + "\n")


def register_one(config: dict[str, Any]) -> Result:
    # Proxy: pool nhiều IP → xoay theo TỪNG acc (dồn 1 IP là bị flag)
    try:
        from canreg.paths import ensure_grok_on_path

        ensure_grok_on_path()
        from grokreg.core.proxy_rotate import next_proxy

        config["proxy"] = next_proxy(config)
    except Exception:
        pass
    t0 = time.time()
    password = resolve_password(config)
    name = resolve_display_name(config)
    save = ROOT / str(config.get("save_file") or "data/accounts.txt")
    email = ""
    hotmail = None
    session = None
    try:
        raise_if_stop()
        session, hotmail, mail_api, azpop, tmail, mailtm, guerrilla = acquire_email(config)
        email = session.address
        log.info("Email=%s provider=%s name=%s", email, session.provider, name)

        tried_codes: set[str] = set()

        def _wait() -> dict[str, str]:
            return wait_canva_mail(
                session,
                config,
                mail_api=mail_api,
                hotmail=hotmail,
                azpop=azpop,
                tmail=tmail,
                mailtm=mailtm,
                guerrilla=guerrilla,
                timeout=int(config.get("timeout_otp") or 180),
                ignore_codes=tried_codes,
            )

        out: dict[str, Any] = {}
        for attempt in range(1, 4):
            out = _run_backend(config, email, password, _wait, name)
            if out.get("status") != "error:email_flagged" or attempt >= 3:
                break
            log.warning("email flagged (%s) — đổi mail %s/3", email, attempt + 1)
            _save(save, email, password, "error:email_flagged")
            if str(config.get("email_provider") or "") == "hotmail":
                break
            if str(getattr(session, "provider", "") or config.get("email_provider") or "") == "tmail_wibu":
                from canreg.tmail_policy import ban_domain, domain_of

                banned = ban_domain(domain_of(email), reason=str(out.get("detail") or "flagged"))
                if banned:
                    log.info("Cấm domain tmail %s (Canva security)", banned)
                tmail_block = dict(config.get("tmail_wibu") or {})
                tmail_block.setdefault("domains", [])
                config["tmail_wibu"] = tmail_block
                config["email_provider"] = "tmail_wibu"
            else:
                retry_cfg = dict(config)
                retry_cfg["email_provider"] = "azpopmail"
                session, hotmail, mail_api, azpop, tmail, mailtm, guerrilla = acquire_email(retry_cfg)
                email = session.address
                log.info("Email mới=%s provider=%s", email, session.provider)
                continue
            session, hotmail, mail_api, azpop, tmail, mailtm, guerrilla = acquire_email(config)
            email = session.address
            log.info("Email mới=%s provider=%s", email, session.provider)

        ok = bool(out.get("ok")) or str(out.get("status") or "").startswith("success")
        status = str(out.get("status") or ("success" if ok else "error:unknown"))
        detail = str(out.get("detail") or out.get("url") or "")[:200]
        if out.get("session"):
            try:
                (ROOT / "data" / "last_session.json").write_text(
                    json.dumps(out["session"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                log.warning("Lưu last_session.json fail: %s", e)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        offer = out.get("offer") if isinstance(out.get("offer"), dict) else {}
        extra = offer.get("summary") or ""
        _save(save, email, password, status, extra)

        if ok and str(getattr(session, "provider", "") or "") == "tmail_wibu":
            try:
                from canreg.tmail_policy import domain_of, good_domains, record_good, HUNT_TARGET

                got = record_good(domain_of(email), email=email)
                if got:
                    ok_list = good_domains()
                    log.info(
                        "Domain tmail OK %s (%s/%s): %s",
                        got,
                        len(ok_list),
                        HUNT_TARGET,
                        ", ".join(ok_list),
                    )
            except Exception as e:
                log.warning("record good tmail: %s", e)
        if ok:
            log.info(
                "  ┌─ CANVA ─────────────────────────────────────────────┐\n"
                "  │ email   : %s\n"
                "  │ name    : %s\n"
                "  │ plan    : %s\n"
                "  │ status  : %s\n"
                "  └───────────────────────────────────────────────────────┘",
                email,
                name,
                offer.get("plan") or offer.get("summary") or "—",
                status,
            )
            try:
                from canreg.gsheets import append_canva_account

                always = config.get("sheet_all_success") is not False
                if always or offer.get("has_offer"):
                    msg = append_canva_account(
                        email,
                        password,
                        status,
                        ts,
                        provider=str(getattr(session, "provider", "") or ""),
                        offer=offer,
                    )
                    log.info("Google Sheet canva: %s", str(msg)[:180])
                else:
                    log.info("Google Sheet bỏ qua %s — chưa có offer", email)
            except Exception as e:
                log.warning("Google Sheet skip: %s", e)
            # reg xong → redeem ngay (codes.txt / redeem.code)
            try:
                from canreg.redeem import load_redeem_code, redeem_one_now

                rcode = load_redeem_code(config)
                block = config.get("redeem") if isinstance(config.get("redeem"), dict) else {}
                after = block.get("after_reg")
                if rcode and after is not False and not config.get("tmail_hunt_new"):
                    log.info("Redeem ngay %s code=%s", email, rcode)
                    rr = redeem_one_now(
                        config,
                        email=email,
                        password=password,
                        session=session,
                        code=rcode,
                        cookies=(
                            out["cookies"]
                            if isinstance(out.get("cookies"), list) and out.get("cookies")
                            else None
                        ),
                    )
                    extra = (extra + " " if extra else "") + f"redeem:{rr.status}"
                    _save(save, email, password, f"redeem:{rr.status}", rr.reason[:80])
                    if rr.status == "SUKSES":
                        # dòng sheet đã ghi lúc reg là Free — upsert lại với gói
                        # vừa nhận từ coupon (appendAccount_ thay đúng dòng cũ).
                        try:
                            from canreg.gsheets import append_canva_account

                            pbody = str((rr.proof or {}).get("body") or "")
                            mday = re.search(r"(\d{1,2})\s*(?:days?|ngày)", pbody, re.I)
                            offer = {
                                "has_offer": True,
                                "plan": "Canva Pro",
                                "remaining": f"{mday.group(1)} ngày" if mday else "",
                            }
                            msg2 = append_canva_account(
                                email,
                                password,
                                "success:SUKSES",
                                rr.ts,
                                provider=str(getattr(session, "provider", "") or ""),
                                offer=offer,
                            )
                            log.info("Google Sheet canva (post-redeem): %s", str(msg2)[:180])
                        except Exception as e2:
                            log.warning("Google Sheet post-redeem skip: %s", e2)
            except Exception as e:
                log.warning("redeem after reg: %s", e)
        if (
            not ok
            and str(getattr(session, "provider", "") or "") == "tmail_wibu"
            and ("otp_timeout" in status or "flagged" in status)
        ):
            try:
                from canreg.tmail_policy import ban_domain, domain_of

                why = "security" if "flagged" in status else "no_otp"
                banned = ban_domain(domain_of(email), reason=why)
                if banned:
                    log.info("Loại domain tmail %s (%s) — lần sau đổi domain", banned, why)
            except Exception as e:
                log.warning("ban tmail domain: %s", e)
        # OTP đã nhận = acc tồn tại — đốt alias kể cả lúc cũ ghi signup_incomplete
        if hotmail and (ok or out.get("otp_accepted")):
            try:
                hotmail.mark_used(session)
                log.info("Hotmail mark_used %s", email)
            except Exception as e:
                log.warning("hotmail mark_used: %s", e)
        return Result(ok, status, email, password, detail, time.time() - t0)
    except StopRequested as e:
        status = f"stopped:{e.reason}"
        if email:
            _save(save, email, password, status)
        return Result(False, status, email, password, duration_sec=time.time() - t0)
    except Exception as e:
        log.exception("fatal: %s", e)
        status = f"error:{str(e)[:100]}"
        if email:
            _save(save, email, password, status)
        return Result(False, status, email, password, str(e), time.time() - t0)


def _run_backend(
    config: dict[str, Any],
    email: str,
    password: str,
    wait_mail,
    name: str,
) -> dict[str, Any]:
    backend = str(config.get("reg_backend") or "browser").strip().lower()
    if backend in ("protocol", "http"):
        log.info("Bỏ HTTP Canva (luôn 400) — Chrome")
    import asyncio

    from canreg.browser import register_browser

    log.info("Backend BROWSER")
    return asyncio.run(
        register_browser(
            config,
            email=email,
            password=password,
            wait_mail=wait_mail,
            display_name=name,
        )
    )


BATCH_STATE = ROOT / "data" / "batch_state.json"


def _state_load() -> dict[str, Any]:
    try:
        d = json.loads(BATCH_STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _state_write(tool: str, *, planned: int, done: int, ok: int, last_email: str) -> None:
    try:
        BATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
        BATCH_STATE.write_text(
            json.dumps(
                {
                    "tool": tool,
                    "planned": planned,
                    "done": done,
                    "ok": ok,
                    "pending": max(0, planned - done),
                    "last_email": last_email,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("Ghi batch_state.json fail: %s", e)


def _state_clear() -> None:
    try:
        if BATCH_STATE.exists():
            BATCH_STATE.unlink()
    except Exception:
        pass


_RL_WORDS = re.compile(r"429|rate[ _-]?limit|too many|throttl|retry[- ]?after", re.I)


def _rate_limit_wait(r) -> float:
    """Giây chờ thêm khi kết quả là rate-limit (429/Retry-After). 0 = bình thường."""
    blob = f"{getattr(r, 'status', '')} {getattr(r, 'detail', '')}"
    m = re.search(r"retry[- ]?after[^\d]*(\d+)", blob, re.I) or re.search(r"(\d+)\s*秒", blob)
    if m:
        return float(min(120, max(5, int(m.group(1)) + 2)))
    if _RL_WORDS.search(blob):
        return 30.0
    return 0.0


def _transient(r) -> bool:
    """Lỗi tạm thời đáng thử lại ngay (mạng/timeout/429/domain hỏng/signup đứt)."""
    blob = f"{getattr(r, 'status', '')} {getattr(r, 'detail', '')}"
    return bool(
        re.search(
            r"timeout|network|connection|temporarily|reset|ssl|429|rate[ _-]?limit"
            r"|incomplete|no_signup_fields|no_email_form|no_pw_form",
            blob,
            re.I,
        )
    )




def _backend_parallel_ok(config: dict[str, Any]) -> bool:
    """Backend HTTP chạy song song sẵn; browser cũng được khi chrome_parallel
    bật (mỗi luồng một debug port + profile riêng)."""
    backend = str(config.get("reg_backend") or "").strip().lower()
    return backend in ("protocol", "http", "github", "pure_http", "") or bool(
        config.get("chrome_parallel")
    )


def _run_batch_threaded(
    config: dict[str, Any], total: int, base_done: int, threads: int, dmin: float, dmax: float
) -> list[Result]:
    """Chạy nhiều luồng register_one song song (batch số lượng cố định).

    Mỗi luồng tự pacing như luồng đơn (anti-flag); checkpoint ghi dưới lock."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()
    done = {"n": 0, "ok": 0, "fin": 0}
    out_all: list[Result] = []
    log.info("Chạy %s luồng song song — %s lượt", threads, total)

    def _worker(wid: int) -> list[Result]:
        cfg_t = config
        if config.get("chrome_parallel"):
            # Browser song song: mỗi luồng một debug port riêng
            cfg_t = dict(config)
            cfg_t["chrome_debug_port"] = int(config.get("chrome_debug_port") or 9844) + wid
        local: list[Result] = []
        while True:
            # claim lượt ngay khi còn slot — 2 luồng không cùng nhận một lượt
            with lock:
                if done["n"] >= total:
                    return local
                done["n"] += 1
                cur = done["n"]
            try:
                raise_if_stop()
            except StopRequested:
                return local
            log.info("======== CANVA [L%s] lượt %s/%s ========", wid + 1, cur, total)
            r = register_one(cfg_t)
            if not r.ok and _transient(r) and int(config.get("retry_transient") or 1):
                log.warning("Lỗi tạm thời (%s) — thử lại ngay 1 lần", r.status)
                r = register_one(cfg_t)
            with lock:
                done["fin"] += 1
                if r.ok:
                    done["ok"] += 1
                _state_write(
                    "CANVA",
                    planned=base_done + total,
                    done=base_done + done["fin"],
                    ok=done["ok"],
                    last_email=r.email,
                )
            local.append(r)
            log.info("Kết quả: %s %s (%.1fs)", r.status, r.email, r.duration_sec)
            wait = random.uniform(dmin, dmax) if r.ok else 3
            rl = _rate_limit_wait(r)
            if rl:
                wait = max(wait, rl)
                log.warning("Rate-limit (%s) — chờ %.0fs rồi thử tiếp", r.status, wait)
            time.sleep(wait)
        return local

    with ThreadPoolExecutor(max_workers=threads) as ex:
        for local in ex.map(_worker, range(threads)):
            out_all.extend(local)
    _state_clear()
    return out_all

def run_batch(config: dict[str, Any], count: int, *, resume: bool = False, threads: int = 1) -> list[Result]:
    until_stop = count <= 0
    n = 10**9 if until_stop else max(1, count)
    dmin = float(config.get("inter_success_delay_min") or 8)
    dmax = float(config.get("inter_success_delay_max") or 20)
    hunt = until_stop and "tmail" in str(config.get("email_provider") or "")
    session_start = 0
    if hunt:
        config = dict(config)
        config["tmail_hunt_new"] = True
        config["timeout_otp"] = min(int(config.get("timeout_otp") or 180), 75)
        redeem = dict(config.get("redeem") or {})
        redeem["after_reg"] = False
        config["redeem"] = redeem
        from canreg.tmail_policy import HUNT_TARGET, good_domains

        session_start = len(good_domains())
        log.info(
            "Hunt tmail trên web: đã có %s domain OK — lần này tìm thêm tối đa %s "
            "(Stop bất cứ lúc nào, Start lại để hunt tiếp)",
            session_start,
            HUNT_TARGET,
        )
    out: list[Result] = []
    checkpoint = not until_stop
    base_done = 0
    if resume and checkpoint:
        st = _state_load()
        if st.get("tool") == "canva" and int(st.get("pending") or 0) > 0:
            base_done = int(st.get("done") or 0)
            n = int(st.get("pending"))
            log.info(
                "RESUME: batch cũ còn %s/%s lượt (đã xong %s, OK %s) — chạy tiếp",
                n, st.get("planned"), base_done, st.get("ok"),
            )
        else:
            log.info("Không có checkpoint hợp lệ — chạy batch mới")

    try:
        threads = max(1, min(8, int(threads or 1)))
    except (TypeError, ValueError):
        threads = 1
    if threads >= 2 and str(config.get("reg_backend") or "").strip().lower() == "browser":
        # Browser song song: bật chế độ port riêng theo luồng
        config = dict(config)
        config["chrome_parallel"] = True
    if threads >= 2:
        if not checkpoint:
            log.warning("Chế độ ∞/until-success chỉ chạy 1 luồng — bỏ --threads")
            threads = 1
        elif not _backend_parallel_ok(config):
            log.warning(
                "Backend %s dùng Chrome port cố định — chưa song song được, chạy 1 luồng",
                config.get("reg_backend"),
            )
            threads = 1
    if threads >= 2:
        return _run_batch_threaded(config, n, base_done, threads, dmin, dmax)
    for i in range(1, n + 1):
        raise_if_stop()
        log.info("======== CANVA %s / %s ========", i, "∞" if until_stop else n)
        r = register_one(config)
        if not r.ok and _transient(r) and int(config.get("retry_transient") or 1):
            log.warning("Lỗi tạm thời (%s) — thử lại ngay 1 lần", r.status)
            r = register_one(config)
        out.append(r)
        log.info("Kết quả: %s %s (%.1fs)", r.status, r.email, r.duration_sec)
        if checkpoint:
            _state_write(
                "canva",
                planned=base_done + n,
                done=base_done + i,
                ok=sum(1 for x in out if x.ok),
                last_email=r.email,
            )

        if hunt:
            from canreg.tmail_policy import HUNT_TARGET, good_domains

            n_ok = len(good_domains())
            gained = n_ok - session_start
            log.info("Hunt session +%s/%s (tổng %s OK)", gained, HUNT_TARGET, n_ok)
            if gained >= HUNT_TARGET:
                log.info(
                    "Đủ +%s domain mới — Stop hoặc Start lại trên web để hunt tiếp",
                    HUNT_TARGET,
                )
                break
        elif hunt and until_stop and r.ok:
            log.info("Tìm được tmail reg được — dừng")
            break
        if until_stop or i < n:
            wait = random.uniform(dmin, dmax) if r.ok else 2
            rl = _rate_limit_wait(r)
            if rl:
                wait = max(wait, rl)
                log.warning("Rate-limit (%s) — chờ %.0fs rồi thử tiếp", r.status, wait)
            time.sleep(wait)
    if checkpoint:
        _state_clear()
    return out
