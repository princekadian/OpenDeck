"""FastAPI application factory: REST API, WebSocket endpoint, static frontend."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from ..branding import PRODUCT_NAME
from ..protocol import PROTOCOL_VERSION
from ..services.config import ConfigError
from ..services.pairing import PairingError
from .admin_api import config_error_response, create_admin_router, require_loopback
from .desktop_api import create_desktop_router
from .lan_guard import LanOnlyMiddleware
from .network import lan_addresses

log = logging.getLogger(__name__)


class PairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    device_name: str = Field(default="iPad", alias="deviceName", max_length=64)


class ClientErrorReport(BaseModel):
    level: Literal["error", "trace"] = "error"
    message: str = Field(max_length=500)
    detail: str = Field(default="", max_length=4000)


class _RateLimiter:
    """Allow `limit` events per `window` seconds per key. Keeps unauthenticated logging cheap."""

    def __init__(self, limit: int, window: float) -> None:
        self._limit, self._window = limit, window
        self._events: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        recent = [t for t in self._events.get(key, []) if now - t < self._window]
        if len(recent) >= self._limit:
            self._events[key] = recent
            return False
        recent.append(now)
        self._events[key] = recent
        return True


client_error_limiter = _RateLimiter(limit=10, window=60.0)
client_trace_limiter = _RateLimiter(limit=120, window=60.0)


def create_app(services) -> FastAPI:  # services: app.Services (avoid import cycle)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        services.hub.bind_loop(asyncio.get_running_loop())
        await services.state_coordinator.refresh()
        services.state_coordinator.start()
        services.obs.start()
        services.monitoring.start()
        yield
        await services.monitoring.stop()
        await services.obs.stop()
        await services.state_coordinator.stop()

    app = FastAPI(title=PRODUCT_NAME, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.add_middleware(LanOnlyMiddleware)
    app.add_exception_handler(ConfigError, config_error_response)  # type: ignore[arg-type]

    public = APIRouter(prefix="/api")
    admin = APIRouter(prefix="/api/admin", dependencies=[Depends(require_loopback)])

    @public.get("/info")
    def info() -> dict:
        return {
            "productName": PRODUCT_NAME,
            "pcName": services.config.pc_name,
            "protocolVersion": PROTOCOL_VERSION,
        }

    @public.post("/pair")
    def pair(body: PairRequest, request: Request) -> dict:
        try:
            device, token = services.pairing.pair(body.code, body.device_name)
        except PairingError as exc:
            log.info("Pairing attempt from %s failed: %s", request.client and request.client.host,
                     exc.code)
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})
        return {"deviceId": device.id, "deviceName": device.name, "token": token}

    @public.post("/client-errors", status_code=204)
    def client_error(body: ClientErrorReport, request: Request) -> None:
        """Dashboard crash reports, so iPad-only failures show up in the PC log."""
        host = request.client.host if request.client else "unknown"
        if body.level == "trace":
            if client_trace_limiter.allow(host):
                log.info("Client trace %s: %s", host, body.message)
            return
        if not client_error_limiter.allow(host):
            return
        log.error("Client error from %s (%s): %s\n%s", host,
                  request.headers.get("user-agent", "?")[:200], body.message, body.detail)

    @admin.get("/status")
    def status() -> dict:
        code, remaining = services.pairing.current_code()
        if services.remote is not None:
            server = services.remote.info()
            port, urls = server["port"], server["urls"]
        else:  # API used without the engine runner (tests)
            port = services.config.port
            urls = [f"http://{ip}:{port}" for ip in lan_addresses()]
        return {
            "productName": PRODUCT_NAME,
            "pcName": services.config.pc_name,
            "port": port,
            "urls": urls,
            "pairing": {"code": code, "expiresIn": int(remaining)},
            "connectedDevices": services.hub.connected_devices(),
            "pairedDevices": [d.model_dump(by_alias=True) for d in services.devices.list()],
        }

    @admin.post("/devices/{device_id}/revoke")
    async def revoke(device_id: str) -> dict:
        if not services.devices.revoke(device_id):
            raise HTTPException(status_code=404, detail="Unknown device.")
        await services.hub.disconnect_device(device_id)
        log.info("Device revoked: %s", device_id)
        return {"ok": True}

    @public.get("/assets/{name}")
    def asset(name: str) -> FileResponse:
        """Icon images for buttons. Content-addressed, so cacheable forever."""
        path = services.assets.path_for(name)
        if path is None:
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/png", headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        })

    app.include_router(public)
    app.include_router(admin)
    app.include_router(create_admin_router(services))
    app.include_router(create_desktop_router(services, require_loopback))

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await services.hub.handle(websocket)

    if services.config.static_dir:
        _mount_spa(app, services.config.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the compiled frontend; unknown non-API paths fall back to index.html."""
    root = static_dir.resolve()
    index = root / "index.html"
    if not index.exists():
        log.warning("Frontend build not found at %s; only the API is served", root)
        return

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    def spa(path: str) -> FileResponse | PlainTextResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            # Vite emits content-hashed names under /assets; cache them forever.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
        if not index.exists():  # frontend being rebuilt during development
            return PlainTextResponse("Dashboard is updating. Reload in a moment.", status_code=503,
                                     headers={"Retry-After": "2"})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
