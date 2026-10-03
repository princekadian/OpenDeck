"""The engine: the backend process (database, actions, monitoring, OBS, device server).

Two ways to run it, same code and services:

  headless   `python -m opendeck` (development, servers): the remote-control server
             starts at once and the process ends with it (Ctrl+C).
  desktop    `OpenDeck.exe --engine --control-port N`, started by the desktop app:
             a private listener on 127.0.0.1:N serves the desktop window, and the
             remote-control server is started/stopped on request (Settings decide whether
             it starts automatically). The desktop app asks it to shut down over HTTP.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

import uvicorn

from . import __version__
from .app import Services, build_app
from .branding import PRODUCT_NAME
from .config import AppConfig
from .server.remote import RemoteServer

log = logging.getLogger(__name__)

CONTROL_START_TIMEOUT_S = 10.0


async def serve(config: AppConfig, *, control_port: int | None = None) -> int:
    """Run until asked to stop. Returns a process exit code."""
    desktop = control_port is not None
    app, services = build_app(config)
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    services.request_shutdown = lambda: loop.call_soon_threadsafe(shutdown.set)
    services.started_at = time.time()

    def remote_address() -> tuple[str, int]:
        settings = services.app_settings
        return settings.server_host, (config.port if config.port_from_env else settings.server_port)

    services.remote = RemoteServer(app, remote_address, lambda: services.app_settings.preferred_address)
    _install_signal_handler(loop, shutdown)

    log.info("%s %s engine starting (pid %d, data %s, mode %s)", PRODUCT_NAME, __version__, os.getpid(),
             config.data_dir, "desktop" if desktop else "headless")
    async with app.router.lifespan_context(app):
        control: uvicorn.Server | None = None
        control_task: asyncio.Task | None = None
        if desktop:
            control = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=control_port, lifespan="off",
                                                    log_config=None, timeout_graceful_shutdown=3))
            control_task = asyncio.create_task(control.serve())
            deadline = time.monotonic() + CONTROL_START_TIMEOUT_S
            while not control.started and not control_task.done() and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            if not control.started:
                log.critical("Engine could not open its private port %s", control_port)
                return 3
            log.info("Engine ready on 127.0.0.1:%d", control_port)

        if not desktop or services.app_settings.auto_start_server:
            info = await services.remote.start()
            if not desktop and info["state"] != "running":
                log.error("%s", info["error"])
                return 1
        if services.remote.state == "running":
            for url in services.remote.info()["urls"]:
                log.info("Remote control: %s", url)

        waiters = [asyncio.create_task(shutdown.wait())]
        if control_task:
            waiters.append(control_task)
        if not desktop:
            waiters.append(asyncio.create_task(_until_remote_ends(services.remote)))
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)

        log.info("Engine shutting down")
        await services.remote.stop()
        if control and control_task and not control_task.done():
            control.should_exit = True
            await asyncio.wait({control_task}, timeout=5)
        for task in waiters:
            if not task.done():
                task.cancel()
    services.audio.close()
    services.db.close()
    log.info("Engine stopped")
    return 0


async def _until_remote_ends(remote: RemoteServer) -> None:
    while remote.state in ("running", "starting", "stopping"):
        await remote.wait_change(remote.version)


def _install_signal_handler(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    """Ctrl+C / termination request -> orderly shutdown (Uvicorn restores this after serving)."""

    def handle(*_args) -> None:
        loop.call_soon_threadsafe(shutdown.set)

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            try:
                signal.signal(sig, handle)
            except (ValueError, OSError):
                pass


def run(config: AppConfig, *, control_port: int | None = None) -> int:
    try:
        return asyncio.run(serve(config, control_port=control_port))
    except KeyboardInterrupt:
        return 0
    except Exception:
        log.critical("Engine crashed", exc_info=True)
        return 2


__all__ = ["run", "serve", "Services"]
