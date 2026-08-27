"""Account health-checker — định kỳ verify acc Grok đã import vào Sub2API.

Cách hoạt động:
- Đọc danh sách acc platform=grok từ admin API của Sub2API (phân trang).
- Trạng thái mỗi acc suy từ usage snapshot (extra.grok_usage_snapshot) và
  status field: 403/expired/banned → DEAD, 200/429/active → ALIVE.
- Acc chưa có snapshot mới → probe quota trực tiếp (giới hạn số probe/lượt
  để không làm nặng Sub2API).
- Kết quả cache vào data/health_check.json. Acc chuyển ALIVE→DEAD so với
  lần chạy trước → gửi notification (Telegram/webhook qua notifier).
- Chạy nền mỗi interval giờ (config: health_check.interval_hours); cũng bấm
  chạy tay được từ UI (POST /api/health/run).

Chưa cấu hình Sub2API → báo not_configured, không crash. Mọi lỗi nuốt.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_FILE = "health_check.json"

# account.status values coi như chết
_DEAD_STATUS = {"expired", "banned", "disabled", "deleted", "error", "invalid"}
# usage snapshot status_code coi như chết
_DEAD_CODES = {401, 403}
_ALIVE_CODES = {200, 429}

MAX_PROBES_PER_RUN = 10  # giới hạn probe trực tiếp mỗi lượt chạy


def _load_cfg(root: Path) -> dict[str, Any]:
    try:
        from grokreg.core.config import load_config

        cfg = load_config()
        return {
            "sub2api": dict(cfg.get("sub2api") or {}),
            "health": dict(cfg.get("health_check") or {}),
        }
    except Exception:
        return {"sub2api": {}, "health": {}}


def _state_path(root: Path) -> Path:
    return root / "data" / STATE_FILE


def load_state(root: Path) -> dict[str, Any]:
    p = _state_path(root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(root: Path, state: dict[str, Any]) -> None:
    p = _state_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        logger.warning("[health] save state failed", exc_info=True)


def _classify(acc: dict[str, Any]) -> tuple[str, int, str]:
    """Trả về (verdict, code, reason). verdict: alive|dead|unknown."""
    status = str(acc.get("status") or "").strip().lower()
    extra = acc.get("extra") if isinstance(acc.get("extra"), dict) else {}
    snap = (
        extra.get("grok_usage_snapshot")
        if isinstance(extra.get("grok_usage_snapshot"), dict)
        else {}
    )
    code = 0
    for src in (snap.get("status_code"), snap.get("code")):
        try:
            code = int(src or 0)
            break
        except (TypeError, ValueError):
            continue
    err = str(snap.get("probe_error") or snap.get("error") or "").lower()

    if status in _DEAD_STATUS:
        return "dead", code, f"status={status}"
    if code in _DEAD_CODES or "403" in err:
        return "dead", code if code else 403, "usage 403/blocked"
    if code in _ALIVE_CODES:
        return "alive", code, ""
    if status in ("active", "running", ""):
        # có snapshot cũ hợp lệ thì tin snapshot
        if snap:
            return "alive", code or 200, ""
        return "unknown", 0, "no snapshot"
    return "unknown", code, f"status={status}"


def run_check(root: Path, *, force_probe: bool = False) -> dict[str, Any]:
    """Chạy 1 lượt health check. Trả summary để UI hiển thị."""
    cfg = _load_cfg(root)
    sub_cfg = cfg["sub2api"]
    base = str(sub_cfg.get("sub2api_url") or "").strip()
    has_auth = bool(
        str(sub_cfg.get("sub2api_api_token") or "").strip()
        or (
            str(sub_cfg.get("sub2api_user") or "").strip()
            and str(sub_cfg.get("sub2api_pass") or "")
        )
    )
    if not base or not has_auth:
        return {
            "ok": False,
            "configured": False,
            "message": "Sub2API chưa cấu hình URL + auth trong config.json",
            "checked_at": time.time(),
            "accounts": [],
            "alive": 0,
            "dead": 0,
            "unknown": 0,
        }

    from grokreg.delivery.sub2api_client import Sub2APIError, client_from_cfg

    client = client_from_cfg(sub_cfg)

    # 1) lấy toàn bộ acc platform=grok (phân trang)
    accounts: list[dict[str, Any]] = []
    page = 1
    while page <= 20:  # hard cap 20*100 = 2000 acc
        try:
            data = client._request_json(
                "GET",
                f"/api/v1/admin/accounts?page={page}&page_size=100&platform=grok",
                timeout=min(30.0, client.timeout),
            )
        except Sub2APIError as e:
            return {
                "ok": False,
                "configured": True,
                "message": f"Lỗi gọi Sub2API: {e}",
                "checked_at": time.time(),
                "accounts": [],
                "alive": 0,
                "dead": 0,
                "unknown": 0,
            }
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [a for a in data if isinstance(a, dict)]
        elif isinstance(data, dict):
            raw = data.get("items") or data.get("accounts") or data.get("list") or []
            if isinstance(raw, list):
                items = [a for a in raw if isinstance(a, dict)]
        if not items:
            break
        accounts.extend(items)
        if len(items) < 100:
            break
        page += 1

    prev = load_state(root)
    prev_results = dict(prev.get("results") or {})

    results: dict[str, Any] = {}
    alive = dead = unknown = 0
    newly_dead: list[str] = []
    probes_left = MAX_PROBES_PER_RUN if force_probe else 0

    for acc in accounts:
        aid = str(acc.get("id") or "")
        if not aid:
            continue
        name = str(acc.get("name") or f"#{aid}")
        verdict, code, reason = _classify(acc)
        if verdict == "unknown" and probes_left > 0:
            try:
                payload = client.probe_quota(int(aid), timeout=12.0)
                snap = payload if isinstance(payload, dict) else {}
                scode = 0
                billing = snap.get("billing")
                for src in (
                    snap.get("status_code"),
                    billing.get("status_code") if isinstance(billing, dict) else 0,
                ):
                    try:
                        scode = int(src or 0)
                        break
                    except (TypeError, ValueError):
                        continue
                if scode in _ALIVE_CODES:
                    verdict, code, reason = "alive", scode, "probed"
                elif scode in _DEAD_CODES:
                    verdict, code, reason = "dead", scode, "probed"
            except Exception:
                pass
            probes_left -= 1

        if verdict == "alive":
            alive += 1
        elif verdict == "dead":
            dead += 1
        else:
            unknown += 1

        was = str((prev_results.get(aid) or {}).get("verdict") or "")
        if verdict == "dead" and was == "alive":
            newly_dead.append(name)

        results[aid] = {
            "name": name,
            "verdict": verdict,
            "code": code,
            "reason": reason,
            "checked_at": time.time(),
        }

    state = {
        "checked_at": time.time(),
        "configured": True,
        "total": len(accounts),
        "alive": alive,
        "dead": dead,
        "unknown": unknown,
        "results": results,
    }
    _save_state(root, state)

    if newly_dead:
        lines = "\n".join(f"• {n}" for n in newly_dead[:15])
        more = f"\n… +{len(newly_dead) - 15} acc nữa" if len(newly_dead) > 15 else ""
        try:
            from web_console import notifier

            notifier.notify(
                "health_dead",
                f"💀 {len(newly_dead)} acc Grok vừa chuyển sang DEAD:\n{lines}{more}",
            )
        except Exception:
            logger.warning("[health] notify failed", exc_info=True)

    return {
        "ok": True,
        "configured": True,
        "checked_at": state["checked_at"],
        "total": len(accounts),
        "alive": alive,
        "dead": dead,
        "unknown": unknown,
        "newly_dead": newly_dead,
        "accounts": [
            {"id": k, **v}
            for k, v in sorted(
                results.items(), key=lambda kv: kv[1].get("name", "")
            )[:500]
        ],
    }


class HealthCheckLoop:
    """Thread nền: chạy check ngay khi start rồi lặp theo interval giờ."""

    def __init__(self, root: Path):
        self.root = root
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="health-check")
        self._thread.start()

    def _interval_sec(self) -> int:
        h = _load_cfg(self.root)["health"].get("interval_hours", 6)
        try:
            hours = float(h)
        except (TypeError, ValueError):
            hours = 6.0
        return max(600, int(hours * 3600))

    def _run(self) -> None:
        # đợi console ổn sau boot rồi mới check đầu tiên
        time.sleep(30)
        while not self._stop:
            try:
                run_check(self.root)
            except Exception:
                logger.warning("[health] loop check failed", exc_info=True)
            # sleep theo bước nhỏ để stop phản hồi nhanh
            deadline = time.time() + self._interval_sec()
            while not self._stop and time.time() < deadline:
                time.sleep(min(30, max(1, deadline - time.time())))