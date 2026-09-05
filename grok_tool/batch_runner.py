"""Compatibility shim — implementation lives in `grokreg.tools.batch_runner`."""
from __future__ import annotations

from grokreg.tools.batch_runner import *  # noqa: F403


if __name__ == "__main__":
    from grokreg.tools.batch_runner import main

    raise SystemExit(main())
