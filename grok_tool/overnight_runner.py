"""Compatibility shim — implementation lives in `grokreg.tools.overnight_runner`."""
from __future__ import annotations

from grokreg.tools.overnight_runner import *  # noqa: F403


if __name__ == "__main__":
    from grokreg.tools.overnight_runner import main

    raise SystemExit(main())
