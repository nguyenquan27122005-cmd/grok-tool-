"""Compatibility shim — implementation lives in `grokreg.tools.export_morning_report`."""
from __future__ import annotations

from grokreg.tools.export_morning_report import *  # noqa: F403


if __name__ == "__main__":
    from grokreg.tools.export_morning_report import main

    raise SystemExit(main())
