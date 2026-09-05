"""Compatibility shim — implementation lives in `grokreg.tools.continue_sub2api`."""
from __future__ import annotations

import asyncio

from grokreg.tools.continue_sub2api import *  # noqa: F403

if __name__ == "__main__":
    from grokreg.tools.continue_sub2api import main

    raise SystemExit(asyncio.run(main()))
