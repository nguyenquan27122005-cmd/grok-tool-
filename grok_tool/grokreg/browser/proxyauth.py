"""Proxy auth cho Chrome qua CDP Fetch — Chrome bỏ credential trong --proxy-server.

`--proxy-server=http://user:pass@host:port` làm mọi navigation fail ngay với
ERR_INVALID_AUTH_CREDENTIALS, nên phải tách user:pass ra: Chrome chạy bare host,
còn challenge 407 được trả lời bằng Fetch.continueWithAuth (PROVIDE_CREDENTIALS).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Pattern không bao giờ khớp URL thật → request thường KHÔNG bị RequestPaused.
# Fetch.authRequired vẫn bắn vì chỉ phụ thuộc handleAuthRequests, không theo pattern.
_PROXY_AUTH_PATTERN = "__no_request_match_proxy_auth__"


def split_proxy_creds(proxy: str) -> tuple[str, str, str]:
    """'http://user:pass@host:port' → ('http://host:port', 'user', 'pass')."""
    p = str(proxy or "").strip()
    if "://" in p and "@" in p:
        scheme, _, rest = p.partition("://")
        cred, _, hostport = rest.rpartition("@")
        if cred and hostport:
            user, _, pwd = cred.partition(":")
            return f"{scheme}://{hostport}", user, pwd
    return p, "", ""


async def setup_proxy_auth(tab: Any, config: dict[str, Any]) -> None:
    """Proxy có user:pass → đăng ký handler CDP Fetch.authRequired trên tab."""
    _, user, pwd = split_proxy_creds(str(config.get("proxy") or ""))
    if not user:
        return
    try:
        from pydoll.commands.fetch_commands import FetchCommands
        from pydoll.protocol.fetch.events import FetchEvent
        from pydoll.protocol.fetch.types import AuthChallengeResponseType

        await tab._execute_command(
            FetchCommands.enable(handle_auth_requests=True, url_pattern=_PROXY_AUTH_PATTERN)
        )

        async def _on_auth(event: dict[str, Any]) -> None:
            try:
                params = event.get("params") or event
                rid = params.get("requestId")
                if rid:
                    await tab.continue_with_auth(
                        rid,
                        AuthChallengeResponseType.PROVIDE_CREDENTIALS,
                        proxy_username=user,
                        proxy_password=pwd,
                    )
            except Exception as e:  # noqa: BLE001 — auth fail không được giết flow
                log.debug("proxy auth continue fail: %s", e)

        await tab.on(FetchEvent.AUTH_REQUIRED.value, _on_auth)
        log.info("Proxy auth CDP sẵn sàng (user=%s)", user)
    except Exception as e:  # noqa: BLE001 — không có auth handler vẫn chạy thử
        log.warning("Không bật được proxy auth CDP: %s", e)
