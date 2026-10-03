"""Application composition root and lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI

from .actions import ActionEngine, ActionRegistry, build_default_registry
from .config import AppConfig
from .db import Database
from .repositories import (
    ButtonRepository, DeviceRepository, PageRepository, ProfileRepository, SettingsRepository,
)
from .protocol import MessageType, message
from .server.http import create_app
from .server.ws import ConnectionHub
from .services.assets import AssetStore
from .services.config import ConfigService
from .actions.builtin.streaming import OBS_ACTION_TYPES
from .actions.runtime import ActionRuntime
from .integrations.obs import ObsIntegration
from .services.obs_settings import load_obs_settings
from .services.audio import AudioService
from .services.app_settings import AppSettings, load_app_settings
from .services.monitoring import MonitoringService
from .services.pairing import PairingService
from .services.runtime_store import RuntimeStateStore
from .services.state_coordinator import StateCoordinator
from .services.seed import seed_defaults, seed_monitor_page
from .services.snapshot import SnapshotService
from .services.state import StateManager

log = logging.getLogger(__name__)


@dataclass
class Services:
    config: AppConfig
    db: Database
    settings: SettingsRepository
    profiles: ProfileRepository
    pages: PageRepository
    buttons: ButtonRepository
    devices: DeviceRepository
    registry: ActionRegistry
    assets: AssetStore
    deck_config: ConfigService
    engine: ActionEngine
    audio: AudioService
    obs: ObsIntegration
    runtime_store: RuntimeStateStore
    states: StateManager
    state_coordinator: StateCoordinator
    snapshots: SnapshotService
    pairing: PairingService
    hub: ConnectionHub
    monitoring: MonitoringService
    app_settings: AppSettings = field(default_factory=AppSettings)
    # Set by the engine runner (engine.py).
    remote: Any = None
    request_shutdown: Callable[[], None] = lambda: None
    started_at: float = 0.0


def build_services(config: AppConfig, registry: ActionRegistry | None = None) -> Services:
    config.ensure_dirs()
    db = Database(config.db_path, backup_dir=config.backup_dir)
    db.migrate()
    settings, profiles, pages = SettingsRepository(db), ProfileRepository(db), PageRepository(db)
    buttons, devices = ButtonRepository(db), DeviceRepository(db)
    seed_defaults(settings, profiles, pages, buttons)
    seed_monitor_page(settings, pages)

    registry = registry or build_default_registry()
    assets = AssetStore(config.assets_dir)
    deck_config = ConfigService(db, settings, profiles, pages, buttons, registry, assets)
    engine = ActionEngine(registry, buttons)
    audio = AudioService()
    obs = ObsIntegration()
    runtime_store = RuntimeStateStore(db)
    states = StateManager()
    snapshots = SnapshotService(deck_config, profiles, pages, buttons, states, registry)
    pairing = PairingService(devices)
    hub = ConnectionHub(server_name=config.pc_name, pairing=pairing, engine=engine,
                        snapshots=snapshots, on_seen=devices.touch)
    coordinator = StateCoordinator(registry, buttons, states, has_devices=hub.has_sessions)
    engine.runtime = coordinator.runtime = ActionRuntime(
        store=runtime_store,
        run_step=engine.run_step,
        navigate=hub.navigate,
        refresh_state=lambda types: coordinator.refresh(types),
        services={"audio": audio, "obs": obs},
    )
    # OBS events (live, recording, scene, mute, visibility) refresh the OBS keys at once.
    obs.set_listener(lambda: coordinator.refresh(OBS_ACTION_TYPES))
    obs.settings = load_obs_settings(settings)
    states.subscribe(hub.on_button_state)
    monitoring = MonitoringService(settings)
    monitoring.bind(hub.publish_monitor, hub.monitor_watchers)

    async def on_monitor_subscribe(session) -> None:
        # Show a recent reading at once (never an old one), then a fresh one follows promptly.
        if (latest := monitoring.recent()) is not None:
            await session.send(message(MessageType.SYSTEM_MONITOR, latest))
        monitoring.forget_last_sent()

    hub.on_monitor_subscribe = on_monitor_subscribe
    deck_config.subscribe(hub.schedule_config_broadcast)
    deck_config.subscribe(hub.schedule(coordinator.refresh))  # new/edited buttons get their state
    return Services(config, db, settings, profiles, pages, buttons, devices, registry, assets,
                    deck_config, engine, audio, obs, runtime_store, states, coordinator, snapshots,
                    pairing, hub, monitoring, load_app_settings(settings))


def build_app(config: AppConfig) -> tuple[FastAPI, Services]:
    services = build_services(config)
    return create_app(services), services
