from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oareg.config import resolve_password
from oareg.log import log
from oareg.mail import acquire_email, wait_openart_code
from oareg.paths import ROOT
from oareg.stop import StopRequested, raise_if_stop


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


def ok_of(out: dict[str, Any]) -> bool:
    return bool(out.get("ok")) or str(out.get("status") or "").startswith("success")


def register_one(config: dict[str, Any]) -> Result:
    # Proxy: pool nhiều IP → xoay theo TỪNG acc (dồn 1 IP là bị flag)
    try:
        from oareg.paths import ensure_grok_on_path

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
            from oareg.turnstile import kick_solver

            kick_solver(config)
        except Exception as e:
            log.warning("kick_solver fail: %s — backend protocol có thể thiếu Turnstile", e)

        def _wait(since_iso: str = "") -> str:
            return wait_openart_code(
                session,
                config,
                mail_api=mail_api,
                azpop=azpop,
                tmail=tmail,
                mailtm=mailtm,
                timeout=int(config.get("timeout_otp") or 180),
                since_iso=since_iso,
            )

        out: dict[str, Any] = {}
        retry_mail = str(config.get("email_flagged_retry") or "azpopmail")
        for attempt in range(1, 4):
            from oareg.protocol import register_protocol

            out = register_protocol(config, email=email, password=password, wait_mail=_wait)
            status_now = str(out.get("status") or "")
            already_used = "not_allowed_access" in status_now or "already in use" in str(out.get("detail") or "").lower()
            # Clerk gộp alias +N về base — 1 hotmail = 1 account OpenArt:
            # success hoặc đã dùng → retire cả mailbox để pool chuyển mail kế.
            if str(getattr(session, "provider", "")) == "hotmail" and hotmail and (ok_of(out) or already_used):
                try:
                    hotmail._retire_mailbox(session)
                    log.info("Retire mailbox %s (1 mail = 1 acc OpenArt)", getattr(session, "mailbox", ""))
                except Exception as e:
                    log.warning("retire mailbox fail: %s", e)
            if status_now != "error:email_flagged" and not (already_used and attempt < 3):
                break
            if already_used:
                log.warning("email đã đăng ký OpenArt (%s) — lấy mailbox khác %s/3", email, attempt + 1)
                _save(save, email, password, "error:email_in_use")
            else:
                log.warning("email bị chặn (%s) — đổi mail %s %s/3", email, retry_mail, attempt + 1)
                _save(save, email, password, "error:email_flagged")
            if str(config.get("email_provider") or "") == retry_mail and not already_used:
                break
            if already_used:
                # giữ provider hotmail — acquire() sẽ pick mailbox kế trong pool
                retry_cfg = dict(config)
                retry_cfg["email_provider"] = "hotmail"
            else:
                retry_cfg = dict(config)
                retry_cfg["email_provider"] = retry_mail
            session, hotmail, mail_api, azpop, tmail, mailtm = acquire_email(retry_cfg)
            email = session.address
            log.info("Email moi=%s provider=%s", email, session.provider)

        ok = ok_of(out)
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
        _save(save, email, password, status)
        if ok:
            try:
                from oareg.gsheets import append_openart_account

                msg = append_openart_account(email, password, status, ts)
                log.info("Google Sheet openart: %s", str(msg)[:160])
            except Exception as e:
                log.error("Google Sheet openart FAIL: %s", e)
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
    from oareg.protocol import register_protocol

    log.info("Backend PROTOCOL (Clerk email_code)")
    return register_protocol(config, email=email, password=password, wait_mail=wait_mail)


_RL_WORDS = re.compile(r"429|rate[ _-]?limit|too many|throttl|retry[- ]?after", re.I)


def _rate_limit_wait(r) -> float:
    blob = f"{getattr(r, 'status', '')} {getattr(r, 'detail', '')}"
    m = re.search(r"retry[- ]?after[^\d]*(\d+)", blob, re.I)
    if m:
        return float(min(120, max(5, int(m.group(1)) + 2)))
    if _RL_WORDS.search(blob):
        return 30.0
    return 0.0


def _transient(r) -> bool:
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
                    "pending": planned - done,
                    "last_email": last_email,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("state write fail: %s", e)


def _state_clear() -> None:
    try:
        BATCH_STATE.unlink(missing_ok=True)
    except OSError:
        pass


def _run_batch_threaded(
    config: dict[str, Any], n: int, base_done: int, threads: int, dmin: float, dmax: float
) -> list[Result]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: list[Result] = []
    log.info("Chạy %s luồng song song (backend HTTP)", threads)
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {ex.submit(register_one, config): i for i in range(n)}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            out.append(r)
            log.info("Ket qua %s/%s: %s %s (%.1fs)", i, n, r.status, r.email, r.duration_sec)
            _state_write(
                "openart",
                planned=base_done + n,
                done=base_done + i,
                ok=sum(1 for x in out if x.ok),
                last_email=r.email,
            )
            time.sleep(random.uniform(dmin, dmax) * 0.4)
    return out


def run_batch(config: dict[str, Any], count: int, *, resume: bool = False, threads: int = 1) -> list[Result]:
    until_stop = count <= 0
    n = 10**9 if until_stop else max(1, count)
    dmin = float(config.get("inter_success_delay_min") or 3)
    dmax = float(config.get("inter_success_delay_max") or 6)
    out: list[Result] = []
    checkpoint = not until_stop
    base_done = 0
    if resume and checkpoint:
        st = _state_load()
        if st.get("tool") == "openart" and int(st.get("pending") or 0) > 0:
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
    if threads >= 2:
        return _run_batch_threaded(config, n, base_done, threads, dmin, dmax)
    for i in range(1, n + 1):
        raise_if_stop()
        log.info("======== OPENART %s / %s ========", i, "∞" if until_stop else n)
        r = register_one(config)
        if not r.ok and _transient(r) and int(config.get("retry_transient") or 1):
            log.warning("Lỗi tạm thời (%s) — thử lại ngay 1 lần", r.status)
            r = register_one(config)
        out.append(r)
        log.info("Ket qua: %s %s (%.1fs)", r.status, r.email, r.duration_sec)
        if checkpoint:
            _state_write(
                "openart",
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
