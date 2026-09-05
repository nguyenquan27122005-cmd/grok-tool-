"""Prefetch signup acc KẾ TIẾP trong lúc acc hiện tại chờ OTP (pattern OpenArt).

Signup z.ai chỉ cần email+password+captcha — KHÔNG cần OTP. Nên trong lúc acc
hiện tại chờ mail verify (60-180s), thread nền làm sẵn hết: cấp mail kế → mint
Aliyun → in-page signup. Stash giữ nguyên mail session + proxy đã dùng để phần
verify sau này chạy cùng session/IP với signup (Aliyun gắn session).
"""

from __future__ import annotations

import threading
from typing import Any

from zaireg.log import log

_stash: list[dict[str, Any]] = []
_lock = threading.Lock()
_working = False


def kick(config: dict[str, Any], max_stash: int = 1) -> None:
    global _working
    with _lock:
        if _working or len(_stash) >= max_stash:
            return
        _working = True
    cfg = dict(config)

    def _bg() -> None:
        global _working
        try:
            from zaireg.api import random_username
            from zaireg.captcha import solve_and_signup
            from zaireg.config import resolve_password
            from zaireg.mail import acquire_email

            try:
                from zaireg.paths import ensure_grok_on_path

                ensure_grok_on_path()
                from grokreg.core.proxy_rotate import next_proxy

                cfg["proxy"] = next_proxy(cfg)
            except Exception:
                pass
            mail = acquire_email(cfg)
            email = mail[0].address
            password = resolve_password(cfg)
            username = random_username()
            log.info("[prefetch] mint+signup nền cho %s (proxy=%s)", email, bool(cfg.get("proxy")))
            br = solve_and_signup(
                cfg, email=email, password=password, username=username, submit=False
            )
            if br.get("signup_ok"):
                # mark alias NGAY để luồng sync kế không acquire trùng email
                # này (mailbox dùng chung alias +0..+4 qua ledger)
                hotmail = mail[1]
                if hotmail:
                    try:
                        hotmail.mark_used(mail[0])
                    except Exception:
                        pass
                with _lock:
                    if len(_stash) < max_stash:
                        _stash.append(
                            {
                                "email": email,
                                "password": password,
                                "username": username,
                                "resp": br.get("resp") or {},
                                "proxy": str(cfg.get("proxy") or ""),
                                "mail": mail,
                            }
                        )
                        log.info("[prefetch] acc kế sẵn sàng trong stash: %s", email)
                        return
            log.info(
                "[prefetch] %s chưa signup_ok (%s) — bỏ, acc sau sẽ mint sync",
                email,
                str(br.get("detail") or br.get("status") or "")[:80],
            )
        except Exception as e:
            log.info("[prefetch] fail: %s", str(e)[:120])
        finally:
            with _lock:
                _working = False

    threading.Thread(target=_bg, daemon=True).start()


def pop() -> dict[str, Any] | None:
    with _lock:
        if _stash:
            entry = _stash.pop(0)
            log.info("[prefetch] dùng acc pre-signup từ stash: %s", entry["email"])
            return entry
        return None
