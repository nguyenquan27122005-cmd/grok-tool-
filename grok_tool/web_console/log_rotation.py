"""Log/data housekeeping — chạy lúc web console khởi động và lặp theo lịch.

Mục tiêu: chạy lâu ngày không phình đĩa.
- Rotate file log lớn (web_daemon.log, web_boot.*.log, last_run*.log):
  quá max_bytes → đổi tên .1, .2 … giữ tối đa `keep` bản cũ.
- Prune network_capture_*.json: chỉ giữ N file mới nhất.
- Prune job log cũ (data/logs/<job_id>.log): xóa file cũ hơn max_age_days.

Mọi lỗi đều nuốt (log warning) — dọn dẹp không bao giờ làm hỏng console.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_LOG_BYTES = 5 * 1024 * 1024      # 5 MB cho mỗi file log runtime
LOG_KEEP = 2                          # giữ tối đa 2 bản rotate cũ
CAPTURE_KEEP = 3                      # giữ 3 network_capture_*.json mới nhất
JOB_LOG_MAX_AGE_DAYS = 14             # job log cũ hơn 14 ngày bị xóa

# File runtime log ở data/ — rotate khi vượt MAX_LOG_BYTES
_RUNTIME_LOGS = (
    "web_daemon.log",
    "web_boot.out.log",
    "web_boot.err.log",
    "last_run.log",
    "last_run2.log",
)


def rotate_file(path: Path, max_bytes: int = MAX_LOG_BYTES, keep: int = LOG_KEEP) -> bool:
    """Rotate 1 file: path → path.1 → path.2 … Trả True nếu đã rotate."""
    try:
        if not path.is_file() or path.stat().st_size <= max_bytes:
            return False
        # đẩy các bản cũ xuống: .(keep-1) bị xóa, .2→.3 …
        for i in range(keep - 1, 0, -1):
            src = path.with_name(f"{path.name}.{i}")
            dst = path.with_name(f"{path.name}.{i + 1}")
            if src.is_file():
                try:
                    dst.unlink()
                except Exception:
                    pass
                src.replace(dst)
        rotated = path.with_name(f"{path.name}.1")
        try:
            rotated.unlink()
        except Exception:
            pass
        path.replace(rotated)
        return True
    except Exception:
        logger.warning("[rotation] rotate %s failed", path, exc_info=True)
        return False


def prune_glob(
    directory: Path,
    pattern: str,
    keep_latest: int = 0,
    max_age_days: float | None = None,
) -> int:
    """Xóa file khớp pattern trong directory.

    - keep_latest=N: giữ N file mới nhất (theo mtime), xóa phần còn lại.
    - max_age_days=X: xóa file cũ hơn X ngày.
    Cả hai cùng đặt thì áp dụng điều kiện nào đúng cũng xóa (trừ N mới nhất).
    """
    removed = 0
    try:
        if not directory.is_dir():
            return 0
        files = [p for p in directory.glob(pattern) if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        cutoff = time.time() - max_age_days * 86400 if max_age_days else None
        for idx, p in enumerate(files):
            too_old = cutoff is not None and p.stat().st_mtime < cutoff
            beyond_keep = keep_latest > 0 and idx >= keep_latest
            if too_old or beyond_keep:
                try:
                    p.unlink()
                    removed += 1
                except Exception:
                    pass
    except Exception:
        logger.warning("[rotation] prune %s/%s failed", directory, pattern, exc_info=True)
    return removed


def cleanup(root: Path) -> dict[str, Any]:
    """Chạy toàn bộ dọn dẹp. Trả report để hiển thị/log."""
    data = root / "data"
    report: dict[str, Any] = {
        "rotated": [],
        "captures_removed": 0,
        "job_logs_removed": 0,
        "freed_bytes": 0,
    }
    try:
        # 1) rotate runtime logs
        for name in _RUNTIME_LOGS:
            p = data / name
            before = p.stat().st_size if p.is_file() else 0
            if rotate_file(p):
                report["rotated"].append(name)
                report["freed_bytes"] += before
        # 2) network capture — chỉ giữ vài file mới nhất
        report["captures_removed"] = prune_glob(data, "network_capture_*.json", keep_latest=CAPTURE_KEEP)
        # 3) job log cũ
        report["job_logs_removed"] = prune_glob(
            data / "logs", "*.log", max_age_days=JOB_LOG_MAX_AGE_DAYS
        )
    except Exception:
        logger.warning("[rotation] cleanup failed", exc_info=True)

    if report["rotated"] or report["captures_removed"] or report["job_logs_removed"]:
        logger.info(
            "[rotation] rotated=%s captures=%s job_logs=%s freed=%.1f KB",
            report["rotated"], report["captures_removed"],
            report["job_logs_removed"], report["freed_bytes"] / 1024,
        )
    return report


class RotationLoop:
    """Thread nền: cleanup ngay khi start rồi lặp mỗi `interval_sec`."""

    def __init__(self, root: Path, interval_sec: int = 6 * 3600):
        self.root = root
        self.interval_sec = max(600, int(interval_sec))
        self._stop = False
        self._thread = None

    def start(self) -> None:
        if self._thread is not None:
            return
        import threading

        self._thread = threading.Thread(target=self._run, daemon=True, name="log-rotation")
        self._thread.start()

    def _run(self) -> None:
        cleanup(self.root)  # dọn ngay lúc boot
        while not self._stop:
            time.sleep(self.interval_sec)
            if self._stop:
                break
            cleanup(self.root)