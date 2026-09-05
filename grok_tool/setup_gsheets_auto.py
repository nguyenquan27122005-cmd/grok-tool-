"""Compatibility shim — implementation lives in `grokreg.tools.setup_gsheets_auto`."""
from __future__ import annotations

from grokreg.tools.setup_gsheets_auto import *  # noqa: F403


if __name__ == "__main__":
    from grokreg.tools.setup_gsheets_auto import main

    raise SystemExit(main())
