from __future__ import annotations

import json
import os
from typing import Any

from gsparkreg.paths import CONFIG_PATH, GROK_ROOT, ROOT


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        example = ROOT / "config.example.json"
        if example.exists():
            return json.loads(example.read_text(encoding="utf-8"))
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_password(cfg: dict[str, Any]) -> str:
    fixed = str(cfg.get("fixed_password") or "").strip()
    if fixed:
        return fixed
    import random
    import string

    n = max(12, int(cfg.get("password_length") or 16))
    upper = random.choice(string.ascii_uppercase)
    lower = random.choice(string.ascii_lowercase)
    digit = random.choice(string.digits)
    sym = random.choice("!@#$%")
    rest = "".join(random.choices(string.ascii_letters + string.digits + "!@#$%", k=n - 4))
    chars = list(upper + lower + digit + sym + rest)
    random.shuffle(chars)
    return "".join(chars)


def random_name() -> tuple[str, str]:
    import random

    first = random.choice(
        ["Liam", "Noah", "Olivia", "Emma", "Mia", "Ava", "Lucas", "Ethan", "Sofia", "Hannah"]
    )
    last = random.choice(
        ["Nguyen", "Tran", "Pham", "Le", "Hoang", "Vu", "Dang", "Bui", "Do", "Ngo"]
    )
    return first, last


def _truthy(val: Any, default: bool = True) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() not in ("0", "false", "no", "off", "")


def claim_free_month(cfg: dict[str, Any]) -> bool:
    env = os.environ.get("GENSPARK_CLAIM")
    if env is not None and str(env).strip() != "":
        return _truthy(env, default=True)
    return _truthy(cfg.get("claim_free_month"), default=True)


def captcha_keys(cfg: dict[str, Any]) -> dict[str, str]:
    """2captcha / YesCaptcha keys — local config, then grok_tool, then env."""
    cap = dict(cfg.get("captcha") or {})
    two = str(
        cap.get("2captcha_key")
        or cfg.get("two_captcha_key")
        or os.environ.get("TWOCAPTCHA_KEY")
        or os.environ.get("TWO_CAPTCHA_KEY")
        or ""
    ).strip()
    yes = str(
        cap.get("yescaptcha_key")
        or cfg.get("yescaptcha_key")
        or os.environ.get("YESCAPTCHA_KEY")
        or ""
    ).strip()
    grok_path = GROK_ROOT / "config.json"
    if grok_path.exists() and (not two or not yes):
        try:
            grok = json.loads(grok_path.read_text(encoding="utf-8"))
        except Exception:
            grok = {}
        ts = dict(grok.get("turnstile") or {}) if isinstance(grok, dict) else {}
        if not two:
            two = str((grok.get("captcha") or {}).get("2captcha_key") or "").strip()
        if not yes:
            yes = str(ts.get("yescaptcha_key") or grok.get("yescaptcha_key") or "").strip()
    return {"2captcha_key": two, "yescaptcha_key": yes}
