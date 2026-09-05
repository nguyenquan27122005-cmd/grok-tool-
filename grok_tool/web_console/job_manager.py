"""Run tool jobs as subprocesses with ring-buffer logs.

- Queue: khi đã đủ `max_concurrent` job đang chạy, job mới vào hàng đợi
  (status "queued") và tự chạy khi có slot trống.
- Persistence: mỗi job kết thúc được ghi 1 dòng vào data/jobs.jsonl
  (params đã redact); full log ghi ra data/logs/<job_id>.log.
- Events: logs/status pushes tới các subscriber (SSE endpoint) qua
  asyncio.Queue thread-safe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Optional

from grokreg.core import winhide

from . import notifier
from . import proxy_pool
from .plugins import get_plugin
from .plugins.base import BaseToolPlugin

logger = logging.getLogger(__name__)


def _safe_put(q: "asyncio.Queue", ev: dict[str, Any]) -> None:
    try:
        q.put_nowait(ev)
    except asyncio.QueueFull:
        pass  # SSE gen() coalesce dồn event — mất 1 tick không sao

# Substrings (lowercased) marking a param/CLI flag as sensitive → masked in logs.
# "accounts"/"codes": ChatGPT params mang nguyên danh sách email|pass|2FA.
_SENSITIVE = (
    "pass", "pwd", "token", "secret", "cookie", "auth", "api_key", "apikey",
    "accounts", "codes", "sso",
)

_ACTIVE = ("pending", "running", "stopping")
_MAX_HISTORY_BYTES = 5 * 1024 * 1024


def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        k: ("***" if any(s in str(k).lower() for s in _SENSITIVE) else v)
        for k, v in params.items()
    }


def _redact_cmd(cmd: list[str]) -> list[str]:
    out: list[str] = []
    redact_next = False
    for arg in cmd:
        if redact_next:
            out.append("***")
            redact_next = False
            continue
        if arg.startswith("-") and "=" in arg:
            name = arg.split("=", 1)[0].lower()
            out.append(f"{name}=***" if any(s in name for s in _SENSITIVE) else arg)
            continue
        if arg.startswith("-") and any(s in arg.lower() for s in _SENSITIVE):
            out.append(arg)
            redact_next = True
            continue
        out.append(arg)
    return out


@dataclass
class Job:
    id: str
    tool_id: str
    params: dict[str, Any]
    status: str = "pending"  # pending|queued|running|stopping|done|error|stopped
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    ended_at: float = 0.0
    exit_code: Optional[int] = None
    error: str = ""
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=4000))
    proc: Any = field(default=None, repr=False)
    log_path: Optional[Path] = field(default=None, repr=False)
    _log_seq: int = 0
    _log_fh: Any = field(default=None, repr=False)
    # manager hook — called (from any thread) after each append / status change
    _on_update: Optional[Callable[[str, str], None]] = field(default=None, repr=False)

    def append_log(self, line: str) -> None:
        self._log_seq += 1
        ts = time.strftime("%H:%M:%S")
        stamped = f"[{ts}] {line.rstrip()}"
        self.logs.append(stamped)
        fh = self._log_fh
        if fh is not None:
            try:
                fh.write(stamped + "\n")
                fh.flush()
            except Exception:
                pass
        if self._on_update is not None:
            try:
                self._on_update(self.id, "log")
            except Exception:
                pass

    def touched(self) -> None:
        """Publish a status/queue event without appending a log line."""
        if self._on_update is not None:
            try:
                self._on_update(self.id, "status")
            except Exception:
                pass

    def snapshot(self, log_from: int = 0) -> dict[str, Any]:
        lines = list(self.logs)
        total = self._log_seq
        # seq of the first line still in the buffer (advances past 4000 appends)
        first = total - len(lines)
        if log_from > 0:
            if log_from < first:
                # buffer wrapped past the offset: client is missing every buffered
                # line, so resend the whole buffer
                chunk = lines
            elif log_from < total:
                chunk = lines[len(lines) - (total - log_from):]
            else:
                chunk = []
        else:
            chunk = lines[-300:]
        snap: dict[str, Any] = {
            "id": self.id,
            "tool_id": self.tool_id,
            # SSE/REST trả ra client — redact cùng chuẩn như jobs.jsonl
            # (params "accounts" chứa email|password|2FA nguyên văn).
            "params": _redact_params(self.params),
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "error": self.error,
            "log_seq": total,
            "logs": chunk,
            "running": self.status in _ACTIVE,
        }
        if self.log_path is not None and self.log_path.is_file():
            snap["log_file"] = str(self.log_path.relative_to(self.log_path.parents[2]))
        return snap


class JobManager:
    def __init__(self, root: Path, max_concurrent: int = 1, max_queue: int = 20):
        self.root = root
        # RLock: start/stop may call helpers that also take the lock
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._current_id: Optional[str] = None
        self._queue: Deque[str] = deque()
        try:
            self.max_concurrent = max(1, int(max_concurrent))
        except (TypeError, ValueError):
            self.max_concurrent = 1
        try:
            self.max_queue = max(0, int(max_queue))
        except (TypeError, ValueError):
            self.max_queue = 20
        self._history_file = root / "data" / "jobs.jsonl"
        self._logs_dir = root / "data" / "logs"
        # (event_loop, queue) pairs — pushed via call_soon_threadsafe
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._load_history()

    # ── persistence ──────────────────────────────────────────────

    def _load_history(self) -> None:
        if not self._history_file.is_file():
            return
        try:
            raw = self._history_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            logger.exception("[jobs] cannot read history %s", self._history_file)
            return
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            try:
                job = Job(
                    id=str(rec["id"]),
                    tool_id=str(rec.get("tool_id", "?")),
                    params=dict(rec.get("params") or {}),
                    status=str(rec.get("status") or "done"),
                    created_at=float(rec.get("created_at") or 0.0),
                    started_at=float(rec.get("started_at") or 0.0),
                    ended_at=float(rec.get("ended_at") or 0.0),
                    exit_code=rec.get("exit_code"),
                    error=str(rec.get("error") or ""),
                )
            except Exception:
                continue
            if job.status in _ACTIVE:
                # process died between runs — mark terminal
                job.status = "stopped" if job.started_at else "error"
                job.error = job.error or "web console khởi động lại — job bị gián đoạn"
            lf = rec.get("log_file")
            if lf:
                p = self.root / str(lf)
                if p.is_file():
                    job.log_path = p
            self._jobs[job.id] = job
        logger.info("[jobs] loaded %s history entries", len(self._jobs))

    def _persist(self, job: Job) -> None:
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            if self._history_file.is_file() and self._history_file.stat().st_size > _MAX_HISTORY_BYTES:
                # keep the latest half by lines
                lines = self._history_file.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines(keepends=True)
                self._history_file.write_text(
                    "".join(lines[len(lines) // 2:]), encoding="utf-8"
                )
            rec = {
                "id": job.id,
                "tool_id": job.tool_id,
                "params": _redact_params(job.params),
                "status": job.status,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "ended_at": job.ended_at,
                "exit_code": job.exit_code,
                "error": job.error[:500],
                "log_file": (
                    str(job.log_path.relative_to(self.root)).replace("\\", "/")
                    if job.log_path
                    else ""
                ),
            }
            with self._history_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("[jobs] persist failed for %s", job.id)

    # ── SSE subscriptions ────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        with self._lock:
            self._subs.append((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(lo, qu) for lo, qu in self._subs if qu is not q]

    def _publish(self, job_id: str, kind: str) -> None:
        with self._lock:
            subs = list(self._subs)
        ev = {"job_id": job_id, "kind": kind}
        for loop, q in subs:
            try:
                # _safe_put chạy trong event loop — client treo làm đầy queue
                # thì DROP event thay vì ném QueueFull vào loop (coalescing ở
                # phía gen() sẽ tự lấy snapshot mới nhất ở tick sau).
                loop.call_soon_threadsafe(_safe_put, q, ev)
            except Exception:
                # loop closed — drop the subscriber
                with self._lock:
                    try:
                        self._subs.remove((loop, q))
                    except ValueError:
                        pass

    # ── public API ───────────────────────────────────────────────

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [
            {
                "id": j.id,
                "tool_id": j.tool_id,
                "status": j.status,
                "params": j.params,
                "created_at": j.created_at,
                "ended_at": j.ended_at,
                "exit_code": j.exit_code,
            }
            for j in items[:limit]
        ]

    def queue_info(self) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(self._queue)
            out = []
            for jid in ids:
                j = self._jobs.get(jid)
                if j is not None and j.status == "queued":
                    out.append({"id": j.id, "tool_id": j.tool_id})
        return out

    def _active_unlocked(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status in _ACTIVE)

    def _current_unlocked(self) -> Optional[Job]:
        if self._current_id and self._current_id in self._jobs:
            j = self._jobs[self._current_id]
            if j.status in _ACTIVE:
                return j
        for j in self._jobs.values():
            if j.status in _ACTIVE:
                return j
        return None

    def current(self) -> Optional[Job]:
        with self._lock:
            return self._current_unlocked()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, tool_id: str, params: dict[str, Any]) -> Job:
        plugin = get_plugin(tool_id)
        if plugin.meta.status == "coming_soon":
            raise RuntimeError(f"Tool '{plugin.meta.name}' chưa sẵn sàng")
        if hasattr(plugin, "preflight"):
            plugin.preflight(params or {}, self.root)

        with self._lock:
            if self._active_unlocked() >= self.max_concurrent:
                if len(self._queue) >= self.max_queue:
                    raise RuntimeError(
                        f"Hàng đợi đã đầy ({self.max_queue}) — thử lại sau."
                    )
                job = Job(id=uuid.uuid4().hex[:12], tool_id=tool_id, params=dict(params or {}))
                job.status = "queued"
                job._on_update = self._publish
                self._jobs[job.id] = job
                self._queue.append(job.id)
                job.append_log(f"=== QUEUED tool={tool_id} (chờ {len(self._queue)} job trước) ===")
                job.touched()
                return job
            job = Job(id=uuid.uuid4().hex[:12], tool_id=tool_id, params=dict(params or {}))
            job._on_update = self._publish
            self._jobs[job.id] = job
            self._current_id = job.id

        self._spawn(job, plugin)
        return job

    def _spawn(self, job: Job, plugin: BaseToolPlugin) -> None:
        t = threading.Thread(target=self._run, args=(job, plugin), daemon=True)
        t.start()

    def _pump(self) -> None:
        """Start queued jobs while there are free slots."""
        while True:
            with self._lock:
                if self._active_unlocked() >= self.max_concurrent or not self._queue:
                    return
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if job is None or job.status != "queued":
                    continue
                job.status = "pending"
                if self._current_id is None or self._current_unlocked() is None:
                    self._current_id = job.id
                try:
                    plugin = get_plugin(job.tool_id)
                except Exception:
                    job.status = "error"
                    job.error = f"tool không tồn tại: {job.tool_id}"
                    job.ended_at = time.time()
                    self._persist(job)
                    job.touched()
                    continue
            self._spawn(job, plugin)

    def stop(self, job_id: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            if job_id:
                job = self._jobs.get(job_id)
            else:
                job = self._current_unlocked()
            if job is None:
                try:
                    get_plugin("grok").stop_signal(self.root)
                except Exception:
                    pass
                return {"ok": True, "message": "Không có job đang chạy — đã gửi STOP"}
            if job.status == "queued":
                try:
                    self._queue.remove(job.id)
                except ValueError:
                    pass
                job.status = "stopped"
                job.ended_at = time.time()
                job.append_log(">>> Hủy khỏi hàng đợi")
                self._persist(job)
                job.touched()
                return {"ok": True, "job_id": job.id, "message": "Đã hủy job trong hàng đợi"}
            if job.status not in _ACTIVE:
                return {"ok": True, "message": f"Job đã {job.status}"}
            job.status = "stopping"
            plugin = get_plugin(job.tool_id)

        try:
            plugin.stop_signal(self.root)
            job.append_log(">>> STOP signal sent (data/STOP + soft stop)")
        except Exception as e:
            job.append_log(f"STOP signal error: {e}")

        proc = job.proc
        if proc and proc.poll() is None:
            # give soft stop a few seconds, then terminate the whole tree (Chrome too)
            def _kill_later():
                time.sleep(8)
                if proc.poll() is None:
                    job.append_log(">>> Force terminate process tree...")
                    try:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                capture_output=True,
                                timeout=15,
                                **winhide.kwargs(),
                            )
                        else:
                            try:
                                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                            except Exception:
                                proc.terminate()
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass

            threading.Thread(target=_kill_later, daemon=True).start()

        return {"ok": True, "job_id": job.id, "message": "Đang dừng..."}

    def _run(self, job: Job, plugin: BaseToolPlugin) -> None:
        if job.status == "stopping":
            job.status = "stopped"
            job.ended_at = time.time()
            job.append_log(">>> Stop trước khi spawn — không chạy")
            self._finish(job)
            return
        job.status = "running"
        job.started_at = time.time()
        job.append_log(f"=== START tool={job.tool_id} params={_redact_params(job.params)} ===")
        try:
            cmd = plugin.build_command(job.params, self.root)
            # Pool proxy chung: bật thì pick 1 proxy (rotate/fixed) và để plugin
            # tự ghi vào kênh nó hiểu (config.json của tool). Lỗi áp dụng không
            # chặn job — chạy tiếp không proxy nhưng báo rõ trong log.
            try:
                proxy, idx, dead = proxy_pool.pick_alive()
                for d in dead:
                    job.append_log(f"PROXY: bỏ proxy chết {d}")
                # luôn gọi — pool tắt thì dọn proxy cũ do pool ghi (marker)
                cmd = plugin.apply_proxy(cmd, dict(job.params), self.root, proxy)
                if proxy:
                    label = f"PROXY: {proxy_pool.mask(proxy)}"
                    if idx >= 0:
                        label += f" (pool #{idx + 1})"
                    job.append_log(label)
                else:
                    job.append_log("PROXY: pool tắt / trống / hết proxy sống — không dùng")
            except Exception as exc:  # noqa: BLE001 — lỗi áp dụng không chặn job
                job.append_log(f"PROXY: bỏ qua — {type(exc).__name__}: {exc}")
            cwd = Path(plugin.cwd(self.root))
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            env["GROK_SKIP_KILL_OLD"] = "1"  # don't kill web console chrome accidentally
            if hasattr(plugin, "env_overrides"):
                env.update(plugin.env_overrides(job.params))  # type: ignore[attr-defined]

            # leftover STOP only — never wipe a Stop the user just clicked
            if job.status != "stopping":
                for stop in (self.root / "data" / "STOP", cwd / "data" / "STOP"):
                    try:
                        if stop.exists():
                            stop.unlink()
                    except Exception:
                        pass

            cmd = winhide.rewrite_python_cmd(cmd)
            job.append_log("CMD: " + " ".join(_redact_cmd(cmd)))

            # full log to disk for this job
            try:
                self._logs_dir.mkdir(parents=True, exist_ok=True)
                job.log_path = self._logs_dir / f"{job.id}.log"
                job._log_fh = job.log_path.open("w", encoding="utf-8", errors="replace")
            except Exception:
                job.log_path = None
                job._log_fh = None

            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **winhide.kwargs(new_group=True),
            )
            job.proc = proc

            assert proc.stdout is not None
            for line in proc.stdout:
                job.append_log(line)
            code = proc.wait()
            job.exit_code = code
            if job.status == "stopping":
                job.status = "stopped"
                job.append_log(f"=== STOPPED exit={code} ===")
            elif code == 0:
                job.status = "done"
                job.append_log("=== DONE OK ===")
            else:
                job.status = "error"
                job.append_log(f"=== DONE with exit={code} ===")
        except Exception as e:
            job.status = "error"
            job.error = str(e)
            job.append_log(f"FATAL: {e}")
        finally:
            job.ended_at = time.time()
            job.proc = None
            if job._log_fh is not None:
                try:
                    job._log_fh.close()
                except Exception:
                    pass
                job._log_fh = None
            self._finish(job)

    def _finish(self, job: Job) -> None:
        self._persist(job)
        job.touched()
        self._notify(job)
        self._pump()

    def _notify(self, job: Job) -> None:
        if job.status not in ("done", "error", "stopped"):
            return
        dur = int(job.ended_at - job.started_at) if job.started_at else 0
        icon = {"done": "✅", "error": "❌", "stopped": "⏹"}.get(job.status, "")
        msg = (
            f"{icon} Job {job.tool_id} [{job.id[:8]}] → {job.status.upper()}"
            f"\nexit={job.exit_code} · thời gian {dur}s"
        )
        if job.error:
            msg += f"\nlỗi: {job.error[:200]}"
        if job.log_path is not None:
            msg += f"\nlog: {job.log_path.name}"
        try:
            notifier.notify(f"job_{job.status}", msg)
        except Exception:
            logger.exception("[jobs] notify failed for %s", job.id)
