from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ssreg.config import resolve_password
from ssreg.log import log
from ssreg.mail import acquire_email
from ssreg.paths import ROOT
from ssreg.stop import StopRequested, raise_if_stop


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


_FIRST = ("Quan", "Nam", "Linh", "Minh", "Huong", "Hung", "Lan", "Tuan", "Mai", "Duc")
_LAST = ("Nguyen", "Tran", "Pham", "Le", "Hoang", "Vu", "Dang", "Bui", "Do", "Ngo")


def _random_name() -> str:
    try:
        from ssreg.paths import ensure_grok_on_path

        ensure_grok_on_path()
        from grokreg.core.helpers import random_name as _shared

        first, last = _shared()
        return f"{first} {last}"
    except Exception:
        return f"{random.choice(_FIRST)} {random.choice(_LAST)}"


def ok_of(out: dict[str, Any]) -> bool:
    return bool(out.get("ok")) or str(out.get("status") or "").startswith("success")


def register_one(config: dict[str, Any]) -> Result:
    # Proxy: pool nhiều IP → xoay theo TỪNG acc (dồn 1 IP là bị flag)
    try:
        from ssreg.paths import ensure_grok_on_path

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
        full_name = str(config.get("fixed_name") or "").strip() or _random_name()
        log.info("Name=%s", full_name)

        from ssreg.protocol import register_protocol

        out: dict[str, Any] = {}
        for attempt in range(1, 4):
            out = register_protocol(config, email=email, password=password, full_name=full_name)
            status_now = str(out.get("status") or "")
            already = status_now == "error:email_in_use"
            # temp mail domain bị chặn → đổi sang provider khác; email đã dùng → đổi mailbox
            if status_now != "error:email_flagged" and not already:
                break
            _save(save, email, password, "error:email_in_use" if already else "error:email_flagged")
            if already:
                if str(getattr(session, "provider", "")) == "hotmail" and hotmail:
                    try:
                        hotmail._retire_mailbox(session)
                    except Exception:
                        pass
                log.warning("email đã dùng — lấy mailbox khác %s/3", attempt + 1)
                retry_cfg = dict(config)
                retry_cfg["email_provider"] = "hotmail"
            else:
                if str(config.get("email_provider") or "") == "hotmail":
                    break
                log.warning("email bị chặn — đổi Hotmail %s/3", attempt + 1)
                retry_cfg = dict(config)
                retry_cfg["email_provider"] = "hotmail"
            session, hotmail, mail_api, azpop, tmail, mailtm = acquire_email(retry_cfg)
            email = session.address
            log.info("Email moi=%s provider=%s", email, session.provider)

        ok = ok_of(out)
        status = str(out.get("status") or ("success" if ok else "error:unknown"))
        detail = str(out.get("detail") or out.get("url") or "")[:200]
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        _save(save, email, password, status)
        if ok:
            try:
                from ssreg.gsheets import append_scispace_account

                msg = append_scispace_account(email, password, status, ts)
                log.info("Google Sheet scispace: %s", str(msg)[:160])
            except Exception as e:
                log.error("Google Sheet scispace FAIL: %s", e)
        if ok and hotmail:
            try:
                hotmail.mark_used(session)
            except Exception as e:
                log.warning("hotmail mark_used: %s", e)
        return Result(ok=ok, status=status, email=email, password=password,
                      detail=detail, duration_sec=time.time() - t0)
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


_RL_WORDS = re.compile(r"429|rate[ _-]?limit|too many|throttl|retry[- ]?after", re.I)


def _rate_limit_wait(r) -> float:
    blob = f"{getattr(r, 'status', '')} {getattr(r, 'detail', '')}"
    if _RL_WORDS.search(blob):
        return 30.0
    return 0.0


def _transient(r) -> bool:
    blob = f"{getattr(r, 'status', '')} {getattr(r, 'detail', '')}"
    return bool(re.search(r"timeout|network|connection|temporarily|reset|ssl", blob, re.I))


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
            json.dumps({"tool": tool, "planned": planned, "done": done, "ok": ok,
                        "pending": planned - done, "last_email": last_email,
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=1),
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
    log.info("Chạy %s luồng song song (HTTP thuần — acc độc lập)", threads)
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {ex.submit(register_one, config): i for i in range(n)}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            out.append(r)
            log.info("Ket qua %s/%s: %s %s (%.1fs)", i, n, r.status, r.email, r.duration_sec)
            _state_write("scispace", planned=base_done + n, done=base_done + i,
                         ok=sum(1 for x in out if x.ok), last_email=r.email)
            time.sleep(random.uniform(dmin, dmax) * 0.4)
    return out


def run_batch(config: dict[str, Any], count: int, *, resume: bool = False, threads: int = 1) -> list[Result]:
    import json

    until_stop = count <= 0
    n = 10**9 if until_stop else max(1, count)
    dmin = float(config.get("inter_success_delay_min") or 2)
    dmax = float(config.get("inter_success_delay_max") or 5)
    out: list[Result] = []
    checkpoint = not until_stop
    base_done = 0
    if resume and checkpoint:
        st = _state_load()
        if st.get("tool") == "scispace" and int(st.get("pending") or 0) > 0:
            base_done = int(st.get("done") or 0)
            n = int(st.get("pending"))
            log.info("RESUME: batch cũ còn %s lượt — chạy tiếp", n)

    try:
        threads = max(1, min(8, int(threads or 1)))
    except (TypeError, ValueError):
        threads = 1
    if threads >= 2:
        if not checkpoint:
            log.warning("Chế độ ∞ chỉ chạy 1 luồng — bỏ --threads")
            threads = 1
        else:
            return _run_batch_threaded(config, n, base_done, threads, dmin, dmax)
    for i in range(1, n + 1):
        raise_if_stop()
        log.info("======== SCISPACE %s / %s ========", i, "∞" if until_stop else n)
        r = register_one(config)
        if not r.ok and _transient(r) and int(config.get("retry_transient") or 1):
            log.warning("Lỗi tạm thời (%s) — thử lại 1 lần", r.status)
            r = register_one(config)
        out.append(r)
        log.info("Ket qua: %s %s (%.1fs)", r.status, r.email, r.duration_sec)
        if checkpoint:
            _state_write("scispace", planned=base_done + n, done=base_done + i,
                         ok=sum(1 for x in out if x.ok), last_email=r.email)
        if until_stop or i < n:
            wait = random.uniform(dmin, dmax) if r.ok else 3
            rl = _rate_limit_wait(r)
            if rl:
                wait = max(wait, rl)
                log.warning("Rate-limit — chờ %.0fs", wait)
            time.sleep(wait)
    if checkpoint:
        _state_clear()
    return out
