from __future__ import annotations

import json
from typing import Any

from nfreg.paths import CONFIG_PATH, ROOT


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
