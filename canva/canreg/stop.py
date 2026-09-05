from __future__ import annotations

import threading

from canreg.paths import DATA

STOP_FILE = DATA / "STOP"
_event = threading.Event()
_reason = ""


class StopRequested(Exception):
    def __init__(self, reason: str = "stop"):
        self.reason = reason or "stop"
        super().__init__(f"Stop requested: {self.reason}")


def is_stop_requested() -> bool:
    return _event.is_set() or STOP_FILE.exists()


def stop_reason() -> str:
    if _reason:
        return _reason
    return "STOP file" if STOP_FILE.exists() else ""


def request_stop(reason: str = "user", *, write_file: bool = True) -> None:
    global _reason
    if not _reason:
        _reason = reason
    _event.set()
    if write_file:
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOP_FILE.write_text(f"stop:{reason}\n", encoding="utf-8")


def clear_stop() -> None:
    global _reason
    _event.clear()
    _reason = ""
    try:
        if STOP_FILE.exists():
            STOP_FILE.unlink()
    except OSError:
        pass


def raise_if_stop() -> None:
    if is_stop_requested():
        raise StopRequested(stop_reason() or "stop")
