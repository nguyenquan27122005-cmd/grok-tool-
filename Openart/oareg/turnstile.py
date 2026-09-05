"""Solve OpenArt (Clerk) Turnstile via grok_tool local solver :5072.

Có token stash: giải trước token cho account KẾ TIẾP trong lúc acc hiện tại
đang đợi OTP (overlap captcha khỏi critical path).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from oareg.log import log

SITEKEY = "0x4AAAAAAAFV93qQdS0ycilX"
SIGNUP_URL = "https://openart.ai/signin"

# Turnstile token single-use, TTL ~5 phút — stash tối đa 2, dùng trong ~2 phút.
_stash: list[str] = []
_lock = threading.Lock()
_prefetching = False


def kick_solver(config: dict[str, Any]) -> None:
    try:
        from oareg.paths import ensure_grok_on_path

        ensure_grok_on_path()
        from services.solver_manager import start_async

        start_async(config)
        log.info("Turnstile solver: auto-start :5072")
    except Exception as e:
        log.debug("solver start: %s", e)


def _solve_now(config: dict[str, Any]) -> str:
    from oareg.paths import ensure_grok_on_path

    ensure_grok_on_path()
    from grokreg.captcha.turnstile_solver_client import ExternalTurnstileSolver

    ts = dict(config.get("turnstile") or {})
    ts.setdefault("solver_url", "http://127.0.0.1:5072")
    ts.setdefault("sitekey", SITEKEY)
    solver = ExternalTurnstileSolver.from_config({"turnstile": ts, **config})
    if not solver.available():
        kick_solver(config)
        for _ in range(25):
            time.sleep(1)
            if solver.available():
                break
    if not solver.available():
        raise RuntimeError("Turnstile solver offline — bat CHAY_SOLVER.bat (:5072)")
    log.info("Turnstile solve sitekey=%s url=%s", SITEKEY[:20], SIGNUP_URL)
    last = ""
    for attempt in range(1, 4):
        try:
            token = solver.solve(url=SIGNUP_URL, site_key=SITEKEY)
        except Exception as e:
            last = str(e)[:120]
            log.warning("Turnstile solve fail %s/3: %s", attempt, last)
            continue
        if token and len(token) >= 20:
            log.info("Turnstile token len=%s", len(token))
            return token
        last = "empty token"
    raise RuntimeError(f"Turnstile x3: {last}")


def prefetch_token(config: dict[str, Any], max_stash: int = 2) -> None:
    """Giải 1 token nền sau → stash (gọi trước lúc cần: trong lúc đợi OTP)."""
    global _prefetching
    with _lock:
        if _prefetching or len(_stash) >= max_stash:
            return
        _prefetching = True

    def _bg() -> None:
        global _prefetching
        try:
            tok = _solve_now(config)
            with _lock:
                if len(_stash) < max_stash:
                    _stash.append(tok)
        except Exception as e:
            log.debug("prefetch token: %s", e)
        finally:
            with _lock:
                _prefetching = False

    threading.Thread(target=_bg, daemon=True).start()


def solve_token(config: dict[str, Any], wait_prefetch: float = 75.0) -> str:
    """Lấy token: ưu tiên stash; nếu prefetch đang chạy thì chờ nó landing
    (tránh giải 2 task song song làm chậm nhau); hết đường mới giải sync."""
    t0 = time.time()
    while time.time() - t0 < wait_prefetch:
        with _lock:
            if _stash:
                return _stash.pop(0)
            if not _prefetching:
                break
        time.sleep(0.5)
    with _lock:
        if _stash:
            return _stash.pop(0)
    return _solve_now(config)
