"""Canva vs tmail domains.

Loại theo nhóm đã fail — rẻ hơn hunt từng domain:
- wibucrypto / autocapcut: OTP tới, Canva security-block
- .org / .edu.vn / .top / .io.vn: form OK, inbox trống
Giữ short *.name.ng (btedra.name.ng đã success).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from canreg.paths import ROOT

BAN_FILE = ROOT / "data" / "tmail_canva_banned.json"
GOOD_FILE = ROOT / "data" / "tmail_canva_good.json"
HUNT_TARGET = 10

HARD_BAN = {
    "wibucrypto.pro",
    "autocapcut.me",
    "autocapcut.tech",
    "autocapcut.email",
    "codedcapcut.email",
    "botuicapcut.social",
    "melvinscharity.org",
    "aban.edu.vn",
    "kaneapp.top",
    "nhatrangcollege.io.vn",
}

# suffix / host đã fail — không cần test từng subdomain
BAN_SUFFIX = (
    ".org",
    ".edu.vn",
    ".io.vn",
    ".top",
    ".me",
    ".email",
    ".social",
    ".tech",
    "wibucrypto.pro",
)

USABLE = re.compile(r"^[a-z]{3,6}\.name\.ng$")

# btedra.name.ng: OTP tới + Canva cho tạo acc (2026-08-19)
PREFER = (
    "btedra.name.ng",
    "aden.name.ng",
    "ames.name.ng",
    "adon.name.ng",
    "alen.name.ng",
    "adix.name.ng",
)


def _load_ban() -> dict:
    try:
        raw = json.loads(BAN_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def banned_domains() -> set[str]:
    extra = {str(k).strip().lower() for k in (_load_ban().get("domains") or []) if str(k).strip()}
    return set(HARD_BAN) | extra


def ban_domain(domain: str, *, reason: str = "security") -> str:
    d = (domain or "").strip().lower()
    if not d:
        return ""
    data = _load_ban()
    seen = [str(x).strip().lower() for x in (data.get("domains") or []) if str(x).strip()]
    if d not in seen:
        seen.append(d)
    data["domains"] = seen
    hits = data.get("hits") if isinstance(data.get("hits"), dict) else {}
    rec = hits.get(d) if isinstance(hits.get(d), dict) else {}
    rec["reason"] = reason
    rec["count"] = int(rec.get("count") or 0) + 1
    rec["ts"] = int(time.time())
    hits[d] = rec
    data["hits"] = hits
    BAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    BAN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def _load_good() -> dict:
    try:
        raw = json.loads(GOOD_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def good_domains() -> list[str]:
    data = _load_good()
    out: list[str] = []
    for d in data.get("domains") or []:
        x = str(d or "").strip().lower()
        if x and is_usable(x) and x not in out:
            out.append(x)
    return out


def record_good(domain: str, *, email: str = "") -> str:
    d = (domain or "").strip().lower()
    if not d or not is_usable(d):
        return ""
    data = _load_good()
    seen = [str(x).strip().lower() for x in (data.get("domains") or []) if str(x).strip()]
    if d not in seen:
        seen.append(d)
    data["domains"] = seen
    hits = data.get("hits") if isinstance(data.get("hits"), dict) else {}
    rec = hits.get(d) if isinstance(hits.get(d), dict) else {}
    rec["count"] = int(rec.get("count") or 0) + 1
    rec["ts"] = int(time.time())
    if email:
        rec["email"] = email
    hits[d] = rec
    data["hits"] = hits
    GOOD_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOOD_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def is_usable(domain: str) -> bool:
    d = (domain or "").strip().lower()
    if not d or d in banned_domains():
        return False
    if any(d == s or d.endswith(s) for s in BAN_SUFFIX):
        return False
    return bool(USABLE.fullmatch(d))


def preferred_domains(extra: list[str] | None = None) -> list[str]:
    out: list[str] = []
    for d in list(PREFER) + list(extra or []):
        x = str(d or "").strip().lower()
        if x and is_usable(x) and x not in out:
            out.append(x)
    return out


def apply_to_tmail_cfg(cfg: dict, *, hunt_new: bool = False) -> dict:
    merged = dict(cfg or {})
    rest = preferred_domains(list(merged.get("domains") or []))
    proven = [d for d in good_domains() if d in rest or is_usable(d)]
    if hunt_new:
        # tìm domain mới: bỏ cái đã OK
        want = [d for d in rest if d not in set(proven)]
        if not want:
            want = list(rest)
    else:
        want = []
        for d in proven + rest:
            if d not in want:
                want.append(d)
    if want:
        merged["domains"] = want
        merged["_canva_pool"] = len(want)
    return merged


def domain_of(email: str) -> str:
    return (email or "").rsplit("@", 1)[-1].strip().lower()
