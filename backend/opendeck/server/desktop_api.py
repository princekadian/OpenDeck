"""Endpoints for the desktop app (this PC only, like the rest of /api/admin).

Server control, application settings, logs, devices, diagnostics. Everything goes
through the same services as the rest of the engine; nothing here runs actions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import sys
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .. import __version__
from ..branding import PRODUCT_NAME
from ..logging_setup import buffer, set_level, tail
from ..protocol import PROTOCOL_VERSION
from ..services.app_settings import AppSettings, save_app_settings
from .network import lan_addresses, lan_interfaces

log = logging.getLogger(__name__)

LONG_POLL_S = 25.0
SSE_HEARTBEAT_S = 15.0


class _Body(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SettingsBody(AppSettings):
    start_with_windows: bool | None = None


class OpenBody(_Body):
    target: Literal["logs", "data", "backups", "remote"]


class RenameBody(_Body):
    name: str = Field(min_length=1, max_length=40)


def create_desktop_router(services, require_loopback) -> APIRouter:  # services: app.Services
    router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_loopback)])
    config = services.config
    cpu_before: list = [None]  # previous GetSystemTimes reading, for CPU % between calls

    def remote():
        if services.remote is None:
            raise HTTPException(status_code=503, detail={"code": "NO_SERVER", "message": "The server manager isn't running."})
        return services.remote

    # ---- health and server control ---------------------------------------------------------

    @router.get("/health")
    def health() -> dict:
        return {
            "ok": True,
            "productName": PRODUCT_NAME,
            "version": __version__,
            "pid": os.getpid(),
            "uptimeSeconds": round(time.time() - services.started_at) if services.started_at else None,
            "database": {"ok": services.db.healthy(), "schemaVersion": services.db.schema_version()},
        }

    @router.get("/server")
    def server_info() -> dict:
        return {**remote().info(), "devices": len(services.hub.connected_devices())}

    @router.get("/server/wait")
    async def server_wait(since: int = Query(0, ge=0)) -> dict:
        """Long poll: answers when the server state changes (or after ~25 s)."""
        await remote().wait_change(since, LONG_POLL_S)
        return {**remote().info(), "devices": len(services.hub.connected_devices())}

    @router.post("/server/{command}")
    async def server_command(command: Literal["start", "stop", "restart"]) -> dict:
        manager = remote()
        log.info("Remote server %s requested from the desktop app", command)
        info = await {"start": manager.start, "stop": manager.stop, "restart": manager.restart}[command]()
        return {**info, "devices": len(services.hub.connected_devices())}

    @router.post("/shutdown", status_code=202)
    def shutdown() -> dict:
        log.info("Engine shutdown requested by the desktop app")
        services.request_shutdown()
        return {"ok": True}

    # ---- settings ----------------------------------------------------------------------

    def settings_view() -> dict:
        from ..native.windows import startup

        return {
            "settings": {**services.app_settings.model_dump(by_alias=True),
                         "startWithWindows": startup.is_enabled()},
            "startWithWindowsAvailable": startup.executable() is not None,
            "interfaces": lan_interfaces(),
            "portFromEnvironment": config.port_from_env,
        }

    @router.get("/app-settings")
    def get_settings() -> dict:
        return settings_view()

    @router.put("/app-settings")
    async def put_settings(body: SettingsBody) -> dict:
        from ..native.windows import startup

        before = services.app_settings
        new = AppSettings.model_validate(body.model_dump(exclude={"start_with_windows"}))
        save_app_settings(services.settings, new)
        services.app_settings = new
        if new.log_level != before.log_level:
            set_level(new.log_level)
        if body.start_with_windows is not None and body.start_with_windows != startup.is_enabled():
            try:
                startup.set_enabled(body.start_with_windows)
                log.info("Start with Windows %s", "enabled" if body.start_with_windows else "disabled")
            except Exception as exc:
                raise HTTPException(status_code=409, detail={"code": "STARTUP_UNAVAILABLE", "message": str(exc)})
        address_changed = (new.server_host, new.server_port) != (before.server_host, before.server_port)
        if address_changed and remote().state in ("running", "error"):
            log.info("Server address changed to %s:%d; restarting the remote server", new.server_host, new.server_port)
            await remote().restart()
        return settings_view()

    # ---- logs ----------------------------------------------------------------------------

    @router.get("/logs")
    def logs(after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000)) -> dict:
        entries = buffer.since(after, limit)
        return {"entries": [e.to_wire() for e in entries], "last": entries[-1].seq if entries else after}

    @router.get("/logs/stream")
    async def logs_stream(after: int = Query(0, ge=0)) -> StreamingResponse:
        """Server-sent events: each new log entry as it is written. No polling."""

        async def events():
            queue = buffer.listen()
            try:
                for entry in buffer.since(after, 500):
                    yield f"data: {json.dumps(entry.to_wire())}\n\n"
                while True:
                    try:
                        entry = await asyncio.wait_for(queue.get(), SSE_HEARTBEAT_S)
                        yield f"data: {json.dumps(entry.to_wire())}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                buffer.unlisten(queue)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/logs/file")
    def log_file(name: Literal["server", "desktop"] = "server", lines: int = Query(1000, ge=1, le=5000)) -> dict:
        path = config.log_dir / f"{name}.log"
        return {"path": str(path), "lines": tail(path, lines)}

    # ---- folders, backup ------------------------------------------------------------------

    @router.post("/open", status_code=204)
    def open_target(body: OpenBody) -> None:
        if body.target == "remote":
            urls = remote().info()["urls"]
            port = remote().info()["port"]
            target = urls[0] if urls else f"http://127.0.0.1:{port}"
        else:
            target = str({"logs": config.log_dir, "data": config.db_path.parent, "backups": config.backup_dir}[body.target])
        os.startfile(target)  # Explorer for folders, the default browser for the URL

    @router.post("/backup")
    def backup() -> dict:
        path = services.db.backup(time.strftime("manual-%Y%m%d-%H%M%S"))
        return {"path": str(path)}

    # ---- devices -------------------------------------------------------------------------

    @router.patch("/devices/{device_id}")
    def rename_device(device_id: str, body: RenameBody) -> dict:
        name = body.name.strip()
        if not name or not services.devices.rename(device_id, name):
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_DEVICE", "message": "Unknown device."})
        services.hub.rename_device(device_id, name)
        log.info("Device %s renamed to %s", device_id, name)
        return {"ok": True}

    # ---- system and diagnostics ----------------------------------------------------------------

    @router.get("/system")
    def system(host_pid: int | None = Query(None, alias="hostPid"), ui_pid: int | None = Query(None, alias="uiPid")) -> dict:
        from ..native.windows import sysinfo

        mem = sysinfo.memory()
        now = sysinfo.cpu_times()
        cpu = sysinfo.cpu_usage(cpu_before[0], now) if cpu_before[0] else None
        cpu_before[0] = now
        processes: dict[str, Any] = {}
        for name, pid in (("engine", os.getpid()), ("desktop", host_pid), ("window", ui_pid)):
            usage = sysinfo.process_usage(pid) if pid else None
            if usage:
                processes[name] = {"pid": usage.pid, "workingSet": usage.working_set, "cpuSeconds": round(usage.cpu_seconds, 2)}
        return {"cpu": round(cpu, 1) if cpu is not None else None,
                "memory": {"total": mem.total, "available": mem.available,
                           "usage": round(100 * (mem.total - mem.available) / mem.total, 1)},
                "processes": processes}

    @router.get("/diagnostics")
    def diagnostics() -> dict:
        info = remote().info() if services.remote else {}
        return {
            "application": f"{PRODUCT_NAME} {__version__}",
            "version": __version__,
            "protocolVersion": PROTOCOL_VERSION,
            "python": platform.python_version(),
            "windows": platform.platform(),
            "packaged": bool(getattr(sys, "frozen", False)),
            "enginePid": os.getpid(),
            "engineUptimeSeconds": round(time.time() - services.started_at) if services.started_at else None,
            "serverState": info.get("state"),
            "serverError": info.get("error"),
            "host": info.get("host"),
            "port": info.get("port"),
            "lanAddresses": lan_addresses(),
            "remoteUrls": info.get("urls", []),
            "connectedDevices": len(services.hub.connected_devices()),
            "pairedDevices": len([d for d in services.devices.list() if not d.revoked]),
            "databasePath": str(config.db_path),
            "databaseOk": services.db.healthy(),
            "schemaVersion": services.db.schema_version(),
            "dataDirectory": str(config.data_dir),
            "logDirectory": str(config.log_dir),
            "backupDirectory": str(config.backup_dir),
            "obs": str(getattr(services.obs, "status", "")),
        }

    return router
