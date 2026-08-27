"""Background monitor cho Turnstile solver (:5072).

Mỗi chu kỳ: probe solver → nếu offline và pipeline cần nó (không dùng
YesCaptcha) thì tự start lại qua services.solver_manager. Offline ≥2 chu kỳ
liên tiếp → gửi notification `solver_down` (1 lần mỗi đợt offline, re-arm
khi solver online trở lại).
"""

from __future__ import annotations

import logging
import threading

from . import notifier

logger = logging.getLogger(__name__)


class SolverMonitor:
    def __init__(self, interval: float = 30.0, down_cycles_notify: int = 2):
        self.interval = max(5.0, interval)
        self.down_cycles_notify = max(1, down_cycles_notify)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._down_cycles = 0
        self._notified = False
        self.last_status: dict = {}

    # ── public ──

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="solver-monitor", daemon=True
        )
        self._thread.start()
        logger.info("[solver-monitor] started (interval %.0fs)", self.interval)

    def stop(self) -> None:
        self._stop_event.set()

    # ── internals ──

    def _config(self) -> dict:
        try:
            from grokreg.core.config import load_config

            return load_config()
        except Exception:
            logger.exception("[solver-monitor] config load failed")
            return {}

    def _tick(self) -> dict:
        from services import solver_manager

        cfg = self._config()
        try:
            solver_manager.configure_from_settings(cfg)
        except Exception:
            pass
        status = solver_manager.get_status()
        self.last_status = dict(status)

        if status.get("online"):
            self._down_cycles = 0
            self._notified = False
            return status

        self._down_cycles += 1
        logger.warning(
            "[solver-monitor] solver offline (cycle %d): %s",
            self._down_cycles,
            status.get("last_error") or "no response",
        )
        # Only auto-start when the pipeline actually needs the local solver
        try:
            needed = solver_manager.should_auto_start(cfg)
        except Exception:
            needed = False
        if needed:
            try:
                solver_manager.ensure_started(cfg)
                status = solver_manager.get_status()
                self.last_status = dict(status)
            except Exception:
                logger.exception("[solver-monitor] auto-start failed")

        if self._down_cycles >= self.down_cycles_notify and not self._notified:
            if status.get("online"):
                self._down_cycles = 0
                self._notified = False
            else:
                self._notified = True
                notifier.notify(
                    "solver_down",
                    "⚠️ Turnstile solver offline và không restart được "
                    f"({status.get('url') or ':5072'})\n"
                    f"lần cuối: {status.get('last_error') or 'không phản hồi'}",
                )
        return status

    def _loop(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self._tick()
            except Exception:
                logger.exception("[solver-monitor] tick failed")


monitor = SolverMonitor()
