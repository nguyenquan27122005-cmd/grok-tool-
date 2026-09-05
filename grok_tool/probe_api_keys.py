"""Compatibility shim — implementation lives in `grokreg.tools.probe_api_keys`."""
from __future__ import annotations

from grokreg.tools.probe_api_keys import *  # noqa: F403


if __name__ == "__main__":
    from grokreg.tools.probe_api_keys import main

    raise SystemExit(main())
