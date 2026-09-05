from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nfreg.config import resolve_password
from nfreg.log import log
from nfreg.mail import acquire_email, wait_mail
from nfreg.paths import ROOT
from nfreg.stop import StopRequested, raise_if_stop, request_stop


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


def _run_backend(config: dict[str, Any], email: str, password: str, wait_fn) -> dict[str, Any]:
    backend = str(config.get("reg_backend") or "browser").strip().lower()
    if backend in ("protocol", "http"):
        log.info("Backend PROTOCOL")
        from nfreg.protocol import register_protocol

        return register_protocol(config, email=email, password=password, wait_mail=wait_fn)
    if backend == "auto":
        from nfreg.protocol import register_protocol

        log.info("Backend AUTO — protocol rồi fallback browser")
        out = register_protocol(config, email=email, password=password, wait_mail=wait_fn)
        if out.get("ok"):
            return out
        log.warning("protocol fail (%s) — fallback browser", out.get("status"))
    import asyncio

    from nfreg.browser import register_browser

    log.info("Backend BROWSER")
    return asyncio.run(register_browser(config, email=email, password=password, wait_mail=wait_fn))


def register_one(config: dict[str, Any]) -> Result:
    # Proxy: pool nhiều IP → xoay theo TỪNG acc (dồn 1 IP là bị flag)
    try:
        from nfreg.paths import ensure_grok_on_path

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
    try:
        raise_if_stop()
        session, hotmail, mail_api, azpop, tmail, mailtm, guerrilla = acquire_email(config)
        email = session.address
        log.info("Email=%s provider=%s", email, session.provider)

        def _wait() -> dict[str, str]:
            return wait_mail(
                session,
                config,
                mail_api=mail_api,
                hotmail=hotmail,
                azpop=azpop,
                tmail=tmail,
                mailtm=mailtm,
                guerrilla=guerrilla,
                timeout=int(config.get("timeout_otp") or 180),
            )

        out = _run_backend(config, email, password, _wait)
        status = str(out.get("status") or ("success" if out.get("ok") else "error:unknown"))
        ok = bool(out.get("ok")) or status in ("need_payment", "success")
        detail = "need_payment" if status == "need_payment" else str(out.get("detail") or out.get("url") or "")[:200]
        if out.get("session"):
            try:
                (ROOT / "data" / "last_session.json").write_text(
                    json.dumps(out["session"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        _save(save, email, password, status, detail)
        sheetable = ok or status in ("need_payment", "success")
        if sheetable:
            try:
                from nfreg.gsheets import append_account

                msg = append_account(
                    email,
                    password,
                    status,
                    ts,
                    provider=str(getattr(session, "provider", "") or ""),
                    extra=detail,
                )
                log.info("Google Sheet netflix: %s", str(msg)[:180])
            except Exception as e:
                log.warning("Google Sheet skip: %s", e)
        if sheetable and hotmail:
            try:
                hotmail.mark_used(session)
            except Exception as e:
                log.warning("hotmail mark_used: %s", e)
        if not ok and hotmail and not str(status).startswith("stopped"):
            # Fail cũng đốt alias (Netflix đã chấm điểm nó) — đánh dấu để lượt sau
            # xoay sang alias khác thay vì lại dùng đúng alias cũ.
            try:
                hotmail.mark_used(session)
                log.info("Alias %s đánh dấu đã thử (fail) — lượt sau xoay alias mới", email)
            except Exception as e:
                log.warning("hotmail mark_used (fail): %s", e)
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
            log.info("======== NETFLIX [L%s] lượt %s/%s ========", wid + 1, cur, total)
            r = register_one(config)
            if not r.ok and _transient(r) and int(config.get("retry_transient") or 1):
                log.warning("Lỗi tạm thời (%s) — thử lại ngay 1 lần", r.status)
                r = register_one(config)
            with lock:
                done["n"] += 1
                if r.ok:
                    done["ok"] += 1
                _state_write(
                    "NETFLIX",
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
    until_success = bool(config.get("until_success"))
    n = 10**9 if (until_stop or until_success) else max(1, count)
    dmin = float(config.get("inter_success_delay_min") or 8)
    dmax = float(config.get("inter_success_delay_max") or 20)
    out: list[Result] = []
    checkpoint = not (until_stop or until_success)
    base_done = 0
    if resume and checkpoint:
        st = _state_load()
        if st.get("tool") == "netflix" and int(st.get("pending") or 0) > 0:
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
        log.info("======== NETFLIX %s / %s ========", i, "∞" if until_stop or until_success else n)
        r = register_one(config)
        if not r.ok and _transient(r) and int(config.get("retry_transient") or 1):
            log.warning("Lỗi tạm thời (%s) — thử lại ngay 1 lần", r.status)
            r = register_one(config)
        out.append(r)
        log.info("Kết quả: %s %s (%.1fs)", r.status, r.email, r.duration_sec)
        if checkpoint:
            _state_write(
                "netflix",
                planned=base_done + n,
                done=base_done + i,
                ok=sum(1 for x in out if x.ok),
                last_email=r.email,
            )

        done = r.ok or r.status in ("need_payment", "success")
        if done and until_success:
            log.info("Tới payment/success — dừng (until_success)")
            request_stop("got_success")
            break
        if until_stop or until_success or i < n:
            wait = random.uniform(dmin, dmax) if done else 3
            rl = _rate_limit_wait(r)
            if rl:
                wait = max(wait, rl)
                log.warning("Rate-limit (%s) — chờ %.0fs rồi thử tiếp", r.status, wait)
            time.sleep(wait)
    if checkpoint:
        _state_clear()
    return out
