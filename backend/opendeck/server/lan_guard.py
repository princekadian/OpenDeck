"""ASGI middleware rejecting HTTP/WebSocket clients outside private networks."""

from __future__ import annotations

import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from .network import is_lan

log = logging.getLogger(__name__)


class LanOnlyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            host = client[0] if client else None
            if not is_lan(host):
                log.warning("Rejected non-LAN client %s", host)
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"text/plain")]})
                    await send({"type": "http.response.body", "body": b"Forbidden"})
                return
        await self.app(scope, receive, send)
