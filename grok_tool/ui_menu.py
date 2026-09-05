"""Compatibility shim — implementation lives in `grokreg.tools.ui_menu`."""
from __future__ import annotations

from grokreg.tools.ui_menu import *  # noqa: F403


if __name__ == "__main__":
    from grokreg.tools.ui_menu import main_menu

    raise SystemExit(main_menu())
