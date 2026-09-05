"""Local Aliyun-captcha solver service cho z.ai (pattern solver :5072 grok_tool).

Mở python này lên (CHAY_SOLVER.bat) là nó nằm nền giải captcha ẩn — reg tool
chỉ POST HTTP thuần tới đây, không dính Chrome. Chrome chạy offscreen trong
process solver, account nào cũng đăng ký in-page ngay trong session đã verify.

API:
  GET  /health → {"ok": true, "busy": bool}
  POST /signup {"email","password","username"} → {"token","signup_ok","resp",...}
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Chrome trong solver là duy nhất — các request xếp hàng
_solve_lock = threading.Lock()


def _solve_signup(body: dict) -> dict:
    from zaireg.captcha import solve_and_signup
    from zaireg.config import load_config

    cfg = load_config()
    proxy = str(body.get("proxy") or "").strip()
    if proxy:
        cfg["proxy"] = proxy
    return solve_and_signup(
        cfg,
        email=str(body.get("email") or ""),
        password=str(body.get("password") or ""),
        username=str(body.get("username") or ""),
        submit=False,
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003 — gọn thay vì mặc định ồn
        pass

    def _send(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        path = (self.path or "").split("?")[0]
        if path in ("/", "/health"):
            self._send(200, {"ok": True, "busy": _solve_lock.locked(), "tool": "zaisolver"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        path = (self.path or "").split("?")[0]
        if path != "/signup":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, {"error": f"bad body: {e}"})
            return
        # email rỗng = mint-only (chờ token, không signup)
        if not _solve_lock.acquire(blocking=False):
            self._send(503, {"error": "solver busy"})
            return
        try:
            out = _solve_signup(body)
            self._send(200, out)
        except Exception as e:
            self._send(500, {"error": str(e)[:200]})
        finally:
            # nghỉ chút giữa 2 solve (giữ khoá để request kế cũng chịu nghỉ) —
            # nhồi liên tục dễ bị Aliyun throttle widget (imgs missing kéo dài)
            import random
            import time as _t

            _t.sleep(random.uniform(2.0, 5.0))
            _solve_lock.release()


def main() -> int:
    import os

    # cờ để zaireg.captcha biết đang nằm TRONG solver — không được tự gọi lại
    # service chính nó (503 self-deadlock)
    os.environ["ZAI_SOLVER_INTERNAL"] = "1"
    p = argparse.ArgumentParser(description="Z.ai Aliyun captcha solver :5073")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5073)
    a = p.parse_args()
    # log kéo captcha ra file — reg tool chỉ thấy kết quả qua HTTP
    import logging
    from pathlib import Path

    from zaireg.log import log, setup_logging

    setup_logging()
    (Path(__file__).resolve().parent / "data").mkdir(exist_ok=True)
    fh = logging.FileHandler(
        Path(__file__).resolve().parent / "data" / "solver.log", encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    log.addHandler(fh)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(
        f"[zaisolver] HTTP http://{a.host}:{a.port} — Chrome offscreen, "
        "giải ẩn khi nhận /signup (giữ cửa sổ này mở)",
        flush=True,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
