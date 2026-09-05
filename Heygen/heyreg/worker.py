from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from heyreg.config import resolve_password
from heyreg.log import log
from heyreg.mail import acquire_email, wait_heygen_mail
from heyreg.paths import ROOT
from heyreg.stop import StopRequested, raise_if_stop


@dataclass
class Result:
    ok: bool
    status: str
    email: str = ""
    password: str = ""
    detail: str = ""
    duration_sec: float = 0.0


def _save(path: Path, email: str, password: str, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{email}|{password}|{status}|{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def register_one(config: dict[str, Any]) -> Result:
    # Proxy: pool nhiều IP → xoay theo TỪNG acc (dồn 1 IP là bị flag)
    try:
        from heyreg.paths import ensure_grok_on_path

        ensure_grok_on_path()
        from grokreg.core.proxy_rotate import next_proxy

        config["proxy"] = next_proxy(config)
    except Exception:
        pass
    t0 = time.time()
    password = resolve_password(config)
    save = ROOT / str(config.get("save_file") or "data/accounts.txt")
    email = ""
    hotmail = None
    session = None
    try:
        raise_if_stop()
        session, hotmail, mail_api, azpop, tmail, mailtm = acquire_email(config)
        email = session.address
        log.info("Email=%s provider=%s", email, session.provider)
        try:
            from heyreg.turnstile import kick_solver

            kick_solver(config)
        except Exception as e:
            log.warning("kick_solver fail: %s — backend protocol có thể thiếu Turnstile", e)

        def _wait():
            return wait_heygen_mail(
                session,
                config,
                mail_api=mail_api,
                hotmail=hotmail,
                azpop=azpop,
                tmail=tmail,
                mailtm=mailtm,
                timeout=int(config.get("timeout_otp") or 180),
            )

        out: dict[str, Any] = {}
        for attempt in range(1, 4):
            out = _run_backend(config, email, password, _wait)
            if out.get("status") != "error:email_flagged" or attempt >= 3:
                break
            log.warning("email flagged (%s) — doi mail azpop %s/3", email, attempt + 1)
            _save(save, email, password, "error:email_flagged")
            if str(config.get("email_provider") or "") == "hotmail":
                break
            retry_cfg = dict(config)
            retry_cfg["email_provider"] = "azpopmail"
            session, hotmail, mail_api, azpop, tmail, mailtm = acquire_email(retry_cfg)
            email = session.address
            log.info("Email moi=%s provider=%s", email, session.provider)

        ok = bool(out.get("ok")) or str(out.get("status") or "").startswith("success")
        status = str(out.get("status") or ("success" if ok else "error:unknown"))
        offer = out.get("offer") if isinstance(out.get("offer"), dict) else {}
        detail = str(out.get("detail") or out.get("url") or "")[:200]
        if ok and offer:
            summary = str(offer.get("summary") or "no_offer")
            log.info(
                "  ┌─ HEYGEN OFFER ──────────────────────────────────────┐\n"
                "  │ email   : %s\n"
                "  │ summary : %s  | plan=%s credits=%s\n"
                "  └──────────────────────────────────────────────────────┘",
                email,
                summary,
                offer.get("plan") or "—",
                offer.get("credits", 0),
            )
            detail = (detail + f" | offer={summary}").strip()[:200]
        if out.get("session"):
            try:
                (ROOT / "data" / "last_session.json").write_text(
                    json.dumps(out["session"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                log.warning("Lưu last_session.json fail: %s", e)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        _save(save, email, password, status)
        if ok:
            # HeyGen: chỉ lên Google Sheet tab heygen — không import Sub2API.
            try:
                from heyreg.gsheets import append_heygen_account

                msg = append_heygen_account(email, password, status, ts)
                log.info("Google Sheet heygen: %s", str(msg)[:160])
            except Exception as e:
                log.error("Google Sheet heygen FAIL: %s — không rebuild cả tab", e)
        if ok and hotmail:
            try:
                hotmail.mark_used(session)
            except Exception as e:
                log.warning("hotmail mark_used: %s", e)
        return Result(
            ok=ok,
            status=status,
            email=email,
            password=password,
            detail=detail,
            duration_sec=time.time() - t0,
        )
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
        return Result(False, status, email, password, duration_sec=time.time() - t0, detail=str(e))


def _run_backend(config: dict[str, Any], email: str, password: str, wait_mail) -> dict[str, Any]:
    backend = str(config.get("reg_backend") or "protocol").strip().lower()
    if backend in ("protocol", "http"):
        log.info("Backend PROTOCOL")
        from heyreg.protocol import register_protocol

        return register_protocol(config, email=email, password=password, wait_mail=wait_mail)
    if backend == "auto":
        from heyreg.protocol import register_protocol

        log.info("Backend AUTO — protocol roi fallback browser")
        out = register_protocol(config, email=email, password=password, wait_mail=wait_mail)
        if out.get("ok"):
            return out
        log.warning("protocol fail (%s) — fallback browser", out.get("status"))
    import asyncio

    from heyreg.browser import register_browser

    log.info("Backend BROWSER")
    return asyncio.run(register_browser(config, email=email, password=password, wait_mail=wait_mail))


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



def _ban_tmail_domain(domain: str) -> None:
    """Ghi nhận domain tmail không nhận được mail HeyGen — lần sau bỏ qua."""
    domain = (domain or "").strip().lower()
    if not domain:
        return
    try:
        f = ROOT / "data" / "tmail_banned.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        banned: list[str] = []
        if f.exists():
            try:
                banned = [d for d in json.loads(f.read_text(encoding="utf-8")) if isinstance(d, str)]
            except Exception:
                banned = []
        if domain not in banned:
            banned.append(domain)
            f.write_text(json.dumps(banned, ensure_ascii=False), encoding="utf-8")
        log.warning("Ban tmail domain %s (không nhận mail HeyGen) — đã ban %s domain", domain, len(banned))
    except Exception as e:
        log.warning("ban tmail domain fail: %s", e)


def _transient(r) -> bool:
    """Lỗi tạm thời đáng thử lại ngay (mạng/timeout/429)."""
    blob = f"{getattr(r, 'status', '')} {getattr(r, 'detail', '')}"
    return bool(re.search(r"timeout|network|connection|temporarily|reset|ssl|429|rate[ _-]?limit", blob, re.I))


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




def _backend_parallel_ok(config: dict[str, Any]) -> bool:
    """Backend HTTP (protocol/github) chạy song song an toàn; browser/gpm/auto
    dùng Chrome port cố định theo config — chưa chạy 2 luồng được."""
    backend = str(config.get("reg_backend") or "").strip().lower()
    return backend in ("protocol", "http", "github", "pure_http", "")


def _run_batch_threaded(
    config: dict[str, Any], total: int, base_done: int, threads: int, dmin: float, dmax: float
) -> list[Result]:
    """Chạy nhiều luồng register_one song song (batch số lượng cố định).

    Mỗi luồng tự pacing như luồng đơn (anti-flag); checkpoint ghi dưới lock."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()
    done = {"n": 0, "ok": 0}
    out_all: list[Result] = []
    log.info("Chạy %s luồng song song — %s lượt", threads, total)

    def _worker(wid: int) -> list[Result]:
        local: list[Result] = []
        while True:
            with lock:
                if done["n"] >= total:
                    return local
                cur = done["n"] + 1
            try:
                raise_if_stop()
            except StopRequested:
                return local
            log.info("======== HEYGEN [L%s] lượt %s/%s ========", wid + 1, cur, total)
            r = register_one(config)
            if not r.ok and _transient(r) and int(config.get("retry_transient") or 1):
                log.warning("Lỗi tạm thời (%s) — thử lại ngay 1 lần", r.status)
                r = register_one(config)
            with lock:
                done["n"] += 1
                if r.ok:
                    done["ok"] += 1
                _state_write(
                    "HEYGEN",
                    planned=base_done + total,
                    done=base_done + done["n"],
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
    out: list[Result] = []
    checkpoint = not until_stop
    base_done = 0
    if resume and checkpoint:
        st = _state_load()
        if st.get("tool") == "heygen" and int(st.get("pending") or 0) > 0:
            base_done = int(st.get("done") or 0)
            n = int(st.get("pending"))
            log.info(
                "RESUME: batch cũ còn %s/%s lượt (đã xong %s, OK %s) — chạy tiếp",
                n, st.get("planned"), base_done, st.get("ok"),
            )
        else:
            log.info("Không có checkpoint hợp lệ — chạy batch mới")

    try:
        threads = max(1, min(4, int(threads or 1)))
    except (TypeError, ValueError):
        threads = 1
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
        log.info("======== HEYGEN %s / %s ========", i, "∞" if until_stop else n)
        r = register_one(config)
        if not r.ok and _transient(r) and int(config.get("retry_transient") or 1):
            retry_cfg = config
            if (str(config.get("email_provider")) == "tmail_wibu"
                    and r.status.startswith("error:protocol_otp_timeout") and "@" in (r.email or "")):
                _ban_tmail_domain(r.email.split("@")[-1])
            # Azpop hôm nay không giao được mail HeyGen (inbox trống sau resend) —
            # retry bằng đường mail khác: Hotmail pool (deliverability tốt nhất).
            if r.status.startswith("error:protocol_otp_timeout") and str(
                config.get("email_provider") or ""
            ).strip().lower() in ("azpopmail", "azpop", "2"):
                retry_cfg = dict(config)
                retry_cfg["email_provider"] = "hotmail"
                log.warning(
                    "Azpop không nhận mail HeyGen (%s) — retry bằng Hotmail pool",
                    r.email,
                )
            else:
                log.warning("Lỗi tạm thời (%s) — thử lại ngay 1 lần", r.status)
            r = register_one(retry_cfg)
        out.append(r)
        log.info("Ket qua: %s %s (%.1fs)", r.status, r.email, r.duration_sec)
        if checkpoint:
            _state_write(
                "heygen",
                planned=base_done + n,
                done=base_done + i,
                ok=sum(1 for x in out if x.ok),
                last_email=r.email,
            )

        if until_stop or i < n:
            wait = random.uniform(dmin, dmax) if r.ok else 3
            rl = _rate_limit_wait(r)
            if rl:
                wait = max(wait, rl)
                log.warning("Rate-limit (%s) — chờ %.0fs rồi thử tiếp", r.status, wait)
            time.sleep(wait)
    if checkpoint:
        _state_clear()
    return out
