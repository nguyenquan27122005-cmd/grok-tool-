from __future__ import annotations

import logging
import sys

log = logging.getLogger("xpilot")


def setup_logging() -> None:
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    log.addHandler(h)
    log.propagate = False
