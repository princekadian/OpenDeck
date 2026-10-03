"""The remote-control server: the network listener phones and tablets connect to.

It is one more Uvicorn listener on the same app and the same services as the rest of
the engine (no second backend): stopping it closes the listening socket and every
device connection, while the editor (on its private loopback listener) keeps working.

States: stopped -> starting -> running -> stopping -> stopped, or error (with a message).
`wait_change` lets the desktop app and tray wait for the next change instead of polling.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Callable
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI

from .network import lan_addresses

log = logging.getLogger(__name__)

State = Literal["stopped", "starting", "running", "stopping", "error"]
START_TIMEOUT_S = 10.0
STOP_TIMEOUT_S = 8.0


def port_free(host: str, port: int) -> bool:
    """True if nothing else listens on host:port. Exclusive bind so Windows doesn't share it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


class RemoteServer:
    def __init__(self, app: FastAPI, settings: Callable[[], tuple[str, int]],
                 preferred_address: Callable[[], str | None] = lambda: None) -> None:
        self._app = app
        self._settings = settings  # -> (host, port), read at each start
        self._preferred = preferred_address
        self.state: State = "stopped"
        self.error: str | None = None
        self.host: str | None = None
        self.port: int | None = None
        self.started_at: float | None = None
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._version = 0
        self._changed = asyncio.Condition()

    # ---- state ----------------------------------------------------------------------------

    async def _set(self, state: State, error: str | None = None) -> None:
        self.state, self.error = state, error
        async with self._changed:
            self._version += 1
            self._changed.notify_all()

    @property
    def version(self) -> int:
        return self._version

    async def wait_change(self, since: int, timeout: float = 25.0) -> int:
        """Return once the state version differs from `since` (or after `timeout`)."""
        async with self._changed:
            try:
                await asyncio.wait_for(self._changed.wait_for(lambda: self._version != since), timeout)
            except asyncio.TimeoutError:
                pass
            return self._version

    def addresses(self) -> list[str]:
        if self.host == "127.0.0.1":
            return []
        found = lan_addresses()
        preferred = self._preferred()
        if preferred and preferred in found:
            found = [preferred] + [a for a in found if a != preferred]
        return found

    def info(self) -> dict[str, Any]:
        host, port = (self.host, self.port) if self.state in ("running", "starting", "stopping") else self._settings()
        addresses = [] if host == "127.0.0.1" else self.addresses()
        return {
            "state": self.state,
            "error": self.error,
            "host": host,
            "port": port,
            "lanOnly": host != "127.0.0.1",
            "addresses": addresses,
            "urls": [f"http://{a}:{port}" for a in addresses],
            "startedAt": self.started_at,
            "uptimeSeconds": round(time.time() - self.started_at) if self.started_at and self.state == "running" else None,
            "version": self._version,
        }

    # ---- lifecycle ------------------------------------------------------------------------

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self.state in ("running", "starting"):
                return self.info()
            host, port = self._settings()
            self.host, self.port = host, port
            await self._set("starting")
            if not port_free(host, port):
                message = f"Port {port} is already in use. Choose another port in Settings, or close the program using it."
                log.error("Remote server not started: port %d is already in use", port)
                await self._set("error", message)
                return self.info()
            config = uvicorn.Config(self._app, host=host, port=port, lifespan="off", log_config=None,
                                    ws_max_size=64 * 1024, ws_ping_interval=20, ws_ping_timeout=20,
                                    timeout_graceful_shutdown=5)
            server = uvicorn.Server(config)
            self._server = server
            self._task = asyncio.create_task(self._serve(server))
            deadline = time.monotonic() + START_TIMEOUT_S
            while not server.started and not self._task.done() and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            if not server.started:
                if not self._task.done():
                    server.should_exit = True
                message = self.error or f"The server could not listen on port {port}."
                await self._set("error", message)
                return self.info()
            self.started_at = time.time()
            log.info("Remote control server running on %s:%d (%s)", host, port,
                     ", ".join(f"http://{a}:{port}" for a in self.addresses()) or "this PC only")
            await self._set("running")
            return self.info()

    async def _serve(self, server: uvicorn.Server) -> None:
        try:
            await server.serve()
        except SystemExit:  # uvicorn exits this way when it cannot bind
            self.error = f"The server could not listen on port {self.port}."
            log.error("Remote server failed to bind %s:%s", self.host, self.port)
        except Exception:
            log.exception("Remote server crashed")
            self.error = "The server stopped unexpectedly. See the logs for details."
        finally:
            if self.state == "running":
                self.started_at = None
                if server.should_exit:  # Ctrl+C or a termination request, not a crash
                    await self._set("stopped")
                else:
                    await self._set("error", self.error or "The server stopped unexpectedly.")

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if self.state in ("stopped",) or self._server is None:
                if self.state == "error":
                    await self._set("stopped")
                return self.info()
            await self._set("stopping")
            log.info("Stopping remote control server (closing device connections)")
            server, task = self._server, self._task
            server.should_exit = True  # stop accepting, close connections, finish in-flight requests
            try:
                await asyncio.wait_for(asyncio.shield(task), STOP_TIMEOUT_S)  # type: ignore[arg-type]
            except asyncio.TimeoutError:
                log.warning("Remote server did not stop in %ss; forcing", STOP_TIMEOUT_S)
                server.force_exit = True
                try:
                    await asyncio.wait_for(task, 3)  # type: ignore[arg-type]
                except (asyncio.TimeoutError, Exception):
                    pass
            self._server = self._task = None
            self.started_at = None
            log.info("Remote control server stopped")
            await self._set("stopped")
            return self.info()

    async def restart(self) -> dict[str, Any]:
        await self.stop()
        return await self.start()

