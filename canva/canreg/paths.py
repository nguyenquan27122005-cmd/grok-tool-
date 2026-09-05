from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG_PATH = ROOT / "config.json"
GROK_ROOT = ROOT.parent / "grok_tool"


def ensure_grok_on_path() -> Path | None:
    if GROK_ROOT.is_dir():
        p = str(GROK_ROOT)
        if p not in sys.path:
            sys.path.insert(0, p)
        return GROK_ROOT
    return None


DATA.mkdir(parents=True, exist_ok=True)
