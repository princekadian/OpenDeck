"""Editor REST API. Loopback-only: the PC is the only place configuration changes."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ..actions import ActionError
from ..native.windows import appinfo, dialogs, display, keyboard, winmgmt
from ..native.windows.session import PlatformError
from ..integrations.obs import ObsError, ObsSettings
from ..services.assets import AssetError
from ..services.monitoring import METRICS, MonitoringSettings
from ..services.obs_settings import save_obs_settings
from ..services.audio import AudioServiceError
from ..services.config import ButtonInput, ConfigError, PageInput, ProfileInput
from .network import is_loopback

log = logging.getLogger(__name__)


def require_loopback(request: Request) -> None:
    """Admin/editor endpoints are only reachable from the PC itself."""
    host = request.client.host if request.client else None
    if not is_loopback(host):
        raise HTTPException(status_code=403, detail="Available on this PC only.")


class _Body(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class OrderBody(_Body):
    ids: list[str] = Field(max_length=500)
    # For buttons: the folder whose contents are reordered (None = the page).
    parent_id: str | None = None


class ActiveProfileBody(_Body):
    profile_id: str


class MoveBody(_Body):
    page_id: str
    parent_id: str | None = None


class EnabledBody(_Body):
    enabled: bool


class PickBody(_Body):
    kind: Literal["exe", "file", "folder", "audio"]


class PathBody(_Body):
    path: str = Field(max_length=1024)


class ObsSettingsBody(_Body):
    enabled: bool
    host: str = Field(default="127.0.0.1", min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.:\[\]-]+$")
    port: int = Field(default=4455, ge=1, le=65535)
    password: str | None = Field(default=None, max_length=256)


async def _obs_list(coro) -> list[str]:
    try:
        return await coro
    except ObsError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc


class DraftActionBody(_Body):
    action_type: str = Field(max_length=64)
    action_config: dict[str, Any] = Field(default_factory=dict)


def config_error_response(_: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={
        "detail": {"code": exc.code, "message": exc.message, "fields": exc.fields}})


def create_admin_router(services) -> APIRouter:  # services: app.Services
    router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_loopback)])
    config = services.deck_config
    picker_lock = asyncio.Lock()

    # ---- configuration tree -----------------------------------------------

    @router.get("/config")
    async def get_config() -> dict:
        return {**config.full_tree(), **services.registry.catalog(), "keys": keyboard.key_catalog()}

    # ---- live choices for action settings ----------------------------------------

    @router.get("/audio-devices")
    async def audio_devices(flow: Literal["output", "input"] = "output") -> dict:
        try:
            return {"devices": await services.audio.devices(flow)}
        except AudioServiceError as exc:
            raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc

    @router.get("/displays")
    async def displays() -> dict:
        try:
            found = await asyncio.to_thread(display.list_displays)
        except PlatformError as exc:
            raise HTTPException(status_code=501, detail={"code": "UNSUPPORTED", "message": str(exc)}) from exc
        return {"displays": [{"id": d.id, "name": d.name, "primary": d.primary} for d in found]}

    # ---- OBS integration ------------------------------------------------------------

    def obs_view() -> dict:
        obs = services.obs
        s = obs.settings
        return {"status": obs.status.value, "message": obs.message, "version": obs.obs_version,
                "settings": {"enabled": s.enabled, "host": s.host, "port": s.port, "hasPassword": bool(s.password)}}

    @router.get("/obs")
    async def obs_get() -> dict:
        return obs_view()

    @router.put("/obs")
    async def obs_put(body: ObsSettingsBody) -> dict:
        current = services.obs.settings
        # The password is write-only: null keeps the stored one, "" clears it.
        password = current.password if body.password is None else body.password
        new = ObsSettings(enabled=body.enabled, host=body.host.strip(), port=body.port, password=password)
        await asyncio.to_thread(save_obs_settings, services.settings, new)
        services.obs.configure(new)
        log.info("OBS settings changed (enabled=%s, %s)", new.enabled, new.url)
        await asyncio.sleep(0)  # let the connection attempt start
        return obs_view()

    @router.get("/obs/scenes")
    async def obs_scenes() -> dict:
        return {"items": await _obs_list(services.obs.scenes())}

    @router.get("/obs/inputs")
    async def obs_inputs(kind: Literal["all", "audio", "video"] = "all") -> dict:
        return {"items": await _obs_list(services.obs.inputs(kind))}

    @router.get("/obs/sources")
    async def obs_sources(scene: str = "") -> dict:
        return {"items": await _obs_list(services.obs.scene_sources(scene))}

    @router.get("/running-apps")
    async def running_apps() -> dict:
        """Apps with a visible window, for picking targets of Close / Focus / Running actions."""
        try:
            windows = await asyncio.to_thread(winmgmt.app_windows)
        except PlatformError as exc:
            raise HTTPException(status_code=501, detail={"code": "UNSUPPORTED", "message": str(exc)}) from exc
        apps: dict[str, dict] = {}
        for w in windows:
            if w.path and w.path.lower() not in apps:
                apps[w.path.lower()] = {"path": w.path, "title": w.title}
        names = await asyncio.gather(*(asyncio.to_thread(appinfo.display_name, a["path"]) for a in apps.values()))
        return {"apps": sorted(({**a, "name": n} for a, n in zip(apps.values(), names)),
                               key=lambda a: a["name"].lower())}

    # ---- profiles ---------------------------------------------------------

    @router.post("/profiles", status_code=201)
    async def create_profile(body: ProfileInput) -> dict:
        return config.create_profile(body).model_dump(by_alias=True)

    @router.patch("/profiles/{profile_id}")
    async def update_profile(profile_id: str, body: ProfileInput) -> dict:
        return config.update_profile(profile_id, body).model_dump(by_alias=True)

    @router.delete("/profiles/{profile_id}", status_code=204)
    async def delete_profile(profile_id: str) -> None:
        config.delete_profile(profile_id)

    @router.post("/profiles/{profile_id}/duplicate", status_code=201)
    async def duplicate_profile(profile_id: str) -> dict:
        return config.duplicate_profile(profile_id).model_dump(by_alias=True)

    @router.put("/profiles-order", status_code=204)
    async def reorder_profiles(body: OrderBody) -> None:
        config.reorder_profiles(body.ids)

    @router.put("/active-profile", status_code=204)
    async def set_active_profile(body: ActiveProfileBody) -> None:
        config.set_active_profile(body.profile_id)

    # ---- pages ------------------------------------------------------------

    @router.post("/profiles/{profile_id}/pages", status_code=201)
    async def create_page(profile_id: str, body: PageInput) -> dict:
        return config.create_page(profile_id, body).model_dump(by_alias=True)

    @router.patch("/pages/{page_id}")
    async def update_page(page_id: str, body: PageInput) -> dict:
        return config.update_page(page_id, body).model_dump(by_alias=True)

    @router.delete("/pages/{page_id}", status_code=204)
    async def delete_page(page_id: str) -> None:
        config.delete_page(page_id)

    @router.post("/pages/{page_id}/duplicate", status_code=201)
    async def duplicate_page(page_id: str) -> dict:
        return config.duplicate_page(page_id).model_dump(by_alias=True)

    @router.put("/profiles/{profile_id}/pages-order", status_code=204)
    async def reorder_pages(profile_id: str, body: OrderBody) -> None:
        config.reorder_pages(profile_id, body.ids)

    # ---- buttons ----------------------------------------------------------

    @router.post("/pages/{page_id}/buttons", status_code=201)
    async def create_button(page_id: str, body: ButtonInput) -> dict:
        return config.create_button(page_id, body).model_dump(by_alias=True)

    @router.patch("/buttons/{button_id}")
    async def update_button(button_id: str, body: ButtonInput) -> dict:
        return config.update_button(button_id, body).model_dump(by_alias=True)

    @router.put("/buttons/{button_id}/enabled")
    async def set_enabled(button_id: str, body: EnabledBody) -> dict:
        return config.set_button_enabled(button_id, body.enabled).model_dump(by_alias=True)

    @router.delete("/buttons/{button_id}", status_code=204)
    async def delete_button(button_id: str) -> None:
        config.delete_button(button_id)

    @router.post("/buttons/{button_id}/duplicate", status_code=201)
    async def duplicate_button(button_id: str) -> dict:
        return config.duplicate_button(button_id).model_dump(by_alias=True)

    @router.post("/buttons/{button_id}/move")
    async def move_button(button_id: str, body: MoveBody) -> dict:
        return config.move_button(button_id, body.page_id, body.parent_id).model_dump(by_alias=True)

    @router.put("/pages/{page_id}/buttons-order", status_code=204)
    async def reorder_buttons(page_id: str, body: OrderBody) -> None:
        config.reorder_buttons(page_id, body.ids, body.parent_id)

    # ---- system monitoring ---------------------------------------------------

    @router.get("/monitoring")
    async def monitoring_settings() -> dict:
        return {"settings": services.monitoring.settings.model_dump(by_alias=True), "metrics": list(METRICS)}

    @router.put("/monitoring")
    async def save_monitoring(body: MonitoringSettings) -> dict:
        saved = services.monitoring.update_settings(body)
        return {"settings": saved.model_dump(by_alias=True), "metrics": list(METRICS)}

    @router.get("/monitoring/live")
    async def monitoring_live() -> dict:
        """Latest reading for the editor preview; polling keeps sampling alive briefly."""
        services.monitoring.lease()
        return services.monitoring.recent() or await services.monitoring.sample_once()

    @router.post("/actions/test")
    async def test_action(body: DraftActionBody) -> dict:
        try:
            outcome = await services.engine.execute_draft(body.action_type, body.action_config)
        except ActionError as exc:
            return {"success": False, "error": {"code": exc.code, "message": exc.message}}
        return {"success": True, "message": outcome.message}

    # ---- Windows helpers --------------------------------------------------

    @router.post("/pick")
    async def pick(body: PickBody) -> dict:
        if picker_lock.locked():
            raise HTTPException(status_code=409, detail={
                "code": "PICKER_OPEN", "message": "A file dialog is already open on the PC."})
        async with picker_lock:
            try:
                path = await asyncio.to_thread(dialogs.pick_path, body.kind)
            except PlatformError as exc:
                raise HTTPException(status_code=501, detail={"code": "UNSUPPORTED",
                                                             "message": str(exc)}) from exc
        return {"path": path}

    @router.post("/app-info")
    async def app_info(body: PathBody) -> dict:
        """Name and icon for an executable (or any file), for auto-filling a new button."""
        if not os.path.isfile(body.path):
            raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND",
                                                         "message": "File not found."})
        name = await asyncio.to_thread(appinfo.display_name, body.path)
        png = await asyncio.to_thread(appinfo.extract_icon_png, body.path)
        icon_ref = None
        if png:
            try:
                icon_ref = services.assets.save_png(png)
            except AssetError as exc:
                log.warning("Extracted icon rejected for %s: %s", body.path, exc)
        return {"name": name, "iconRef": icon_ref}

    @router.post("/icons", status_code=201)
    async def upload_icon(request: Request) -> dict:
        """Raw PNG body. The editor converts PNG/JPG/SVG to a ≤256 px PNG before upload."""
        if int(request.headers.get("content-length") or 0) > 1_000_000:
            raise HTTPException(status_code=413, detail={"code": "TOO_LARGE",
                                                         "message": "Icon is too large."})
        if request.headers.get("content-type") != "image/png":
            raise HTTPException(status_code=415, detail={"code": "UNSUPPORTED_TYPE",
                                                         "message": "Upload a PNG image."})
        data = await request.body()
        try:
            return {"iconRef": services.assets.save_png(data)}
        except AssetError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_ICON",
                                                         "message": str(exc)}) from exc

    return router
