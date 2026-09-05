"""One-shot Claude reg with a dedicated hotmails file (does not pick other pool accs)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from claudereg.config import load_config
from claudereg.log import log, setup_logging
from claudereg.stop import clear_stop
from claudereg.worker import run_batch


def main() -> int:
    setup_logging()
    cfg = load_config()
    cfg["email_provider"] = "hotmail"
    cfg["hotmail_list"] = str(ROOT / "data" / "hotmail_one.txt")
    cfg["hotmail_max_aliases"] = 1
    cfg["reg_backend"] = "browser"  # GPMLogin not running
    cfg["google_sheets"] = dict(cfg.get("google_sheets") or {})
    cfg["google_sheets"]["enabled"] = False
    clear_stop()
    log.info("One-shot AmparoBruner16824@hotmail.com backend=browser")
    results = run_batch(cfg, 1)
    if not results:
        return 1
    r = results[0]
    log.info("DONE ok=%s status=%s email=%s detail=%s", r.ok, r.status, r.email, r.detail[:160])
    return 0 if r.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
