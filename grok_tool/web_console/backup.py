"""Auto-backup data quan trọng theo ngày.

Backup mỗi ngày 1 lần vào data/backups/<YYYY-MM-DD>/:
- config.json           (secrets — giữ local, không đẩy GitHub)
- data/accounts.txt     (ledger acc)
- data/hotmails.txt     (pool Hotmail)
- data/proxy_pool.json, data/jobs.jsonl, data/sub2api_name_counter.json

Danh sách file có thể override trong config.json:
    "backup": { "keep_days": 14, "files": ["config.json", "data/..."] }

- Chạy 1 lần ngay khi web boot + thread nền check mỗi giờ (đổi ngày → backup).
- Giữ tối đa keep_days thư mục ngày gần nhất, cũ hơn tự xóa.
- Mọi lỗi nuốt (log warning) — backup không bao giờ làm hỏng console.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = "backups"
DEFAULT_KEEP_DAYS = 14
CHECK_INTERVAL_SEC = 3600  # check mỗi giờ — đổi ngày là backup

# File mặc định đưa vào backup (đường dẫn tương đối ROOT)
DEFAULT_FILES = (
    "config.json",
    "data/accounts.txt",
    "data/hotmails.txt",
    "data/proxy_pool.json",
    "data/jobs.jsonl",
    "data/sub2api_name_counter.json",
)


def _cfg(root: Path) -> dict[str, Any]:
    try:
        from grokreg.core.config import load_config

        cfg = load_config().get("backup") or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _file_list(root: Path) -> list[str]:
    custom = _cfg(root).get("files")
    if isinstance(custom, list) and custom:
        return [str(x) for x in custom]
    return list(DEFAULT_FILES)


def _keep_days(root: Path) -> int:
    try:
        return max(1, int(_cfg(root).get("keep_days") or DEFAULT_KEEP_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_KEEP_DAYS


def backups_dir(root: Path) -> Path:
    return root / "data" / BACKUP_DIR_NAME
def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _is_date(name: str) -> bool:
    try:
        datetime.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def run_backup(root: Path) -> dict[str, Any]:
    """Backup 1 lượt (idempotent trong ngày — folder hôm nay có rồi thì bỏ qua)."""
    dest_root = backups_dir(root) / today_key()
    report: dict[str, Any] = {
        "date": today_key(),
        "skipped": False,
        "copied": [],
        "missing": [],
        "bytes": 0,
    }
    if (dest_root / ".done").is_file():
        # folder hôm nay đã backup HOÀN CHỈNH — run giữa chừng chết thì không
        # có marker, lần chạy sau sẽ chép đè bổ sung thay vì skip cả ngày.
        report["skipped"] = True
        return report

    for rel in _file_list(root):
        src = root / rel
        if not src.is_file():
            report["missing"].append(rel)
            continue
        try:
            dest_root.mkdir(parents=True, exist_ok=True)
            name = Path(rel).name  # flat: giữ nguyên tên file trong folder ngày
            dest = dest_root / name
            if dest.exists():  # trùng tên từ thư mục khác → prefix full path
                dest = dest_root / rel.replace("/", "_").replace("\\", "_")
            shutil.copy2(src, dest)
            report["copied"].append(rel)
            report["bytes"] += dest.stat().st_size
        except Exception:
            logger.warning("[backup] copy %s failed", rel, exc_info=True)

    try:
        (dest_root / ".done").write_text("ok", encoding="utf-8")
    except Exception:
        logger.warning("[backup] cannot write .done marker", exc_info=True)

    report["pruned_days"] = prune_old(root)
    if report["copied"]:
        logger.info(
            "[backup] %s: %d file (%.1f KB)",
            report["date"], len(report["copied"]), report["bytes"] / 1024,
        )
    return report


def prune_old(root: Path) -> int:
    """Xóa folder ngày cũ hơn keep_days. Trả số folder đã xóa."""
    keep = _keep_days(root)
    base = backups_dir(root)
    removed = 0
    cutoff = (datetime.now() - timedelta(days=keep)).strftime("%Y-%m-%d")
    try:
        if not base.is_dir():
            return 0
        for d in sorted(base.iterdir()):
            # chỉ đụng folder dạng YYYY-MM-DD — an toàn với file khác
            if not (d.is_dir() and _is_date(d.name)):
                continue
            if d.name < cutoff:
                try:
                    shutil.rmtree(d)
                    removed += 1
                except Exception:
                    pass
    except Exception:
        logger.warning("[backup] prune failed", exc_info=True)
    return removed


def list_backups(root: Path) -> dict[str, Any]:
    """Danh sách backup hiện có cho UI/API."""
    base = backups_dir(root)
    out: list[dict[str, Any]] = []
    try:
        if base.is_dir():
            for d in sorted(base.iterdir(), reverse=True):
                if not (d.is_dir() and _is_date(d.name)):
                    continue
                files = [p.name for p in sorted(d.iterdir()) if p.is_file()]
                size = sum(p.stat().st_size for p in d.iterdir() if p.is_file())
                out.append({"date": d.name, "files": files, "bytes": size})
    except Exception:
        logger.warning("[backup] list failed", exc_info=True)
    return {
        "dir": str(backups_dir(root)),
        "keep_days": _keep_days(root),
        "today_backed_up": bool(out and out[0]["date"] == today_key()),
        "backups": out,
    }


class BackupLoop:
    """Thread nền: backup ngay khi start rồi check mỗi giờ."""

    def __init__(self, root: Path, interval_sec: int = CHECK_INTERVAL_SEC):
        self.root = root
        self.interval_sec = max(60, int(interval_sec))
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="auto-backup")
        self._thread.start()

    def _run(self) -> None:
        try:
            run_backup(self.root)
        except Exception:
            logger.warning("[backup] initial run failed", exc_info=True)
        while not self._stop:
            time.sleep(self.interval_sec)
            if self._stop:
                break
            try:
                run_backup(self.root)
            except Exception:
                logger.warning("[backup] scheduled run failed", exc_info=True)

    def stop(self) -> None:
        self._stop = True