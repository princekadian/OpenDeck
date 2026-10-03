"""Application settings (server address, tray, logging), stored in the settings table as JSON.

"Start with Windows" is not stored here: its truth is the Run key in the registry
(see native.windows.startup), so it can't disagree with what Windows will do.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from ..branding import DEFAULT_PORT
from ..repositories import SettingsRepository

log = logging.getLogger(__name__)

SETTINGS_KEY = "app"


class AppSettings(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    # 0.0.0.0 = reachable from devices on the local network; 127.0.0.1 = this PC only.
    server_host: Literal["0.0.0.0", "127.0.0.1"] = "0.0.0.0"
    server_port: int = Field(default=DEFAULT_PORT, ge=1024, le=65535)
    # Start the remote-control server when the app starts.
    auto_start_server: bool = True
    # Closing the window keeps the app (and server) running in the notification area.
    minimize_to_tray: bool = True
    # LAN address shown first (QR code, copy). None = the one Windows routes through.
    preferred_address: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("preferred_address")
    @classmethod
    def _address(cls, value: str | None) -> str | None:
        if not value:
            return None
        ipaddress.IPv4Address(value)  # raises for anything else
        return value


def load_app_settings(settings: SettingsRepository) -> AppSettings:
    raw = settings.get(SETTINGS_KEY)
    if not raw:
        return AppSettings()
    try:
        return AppSettings.model_validate_json(raw)
    except ValueError:
        log.warning("Application settings were unreadable; using defaults")
        return AppSettings()


def save_app_settings(settings: SettingsRepository, value: AppSettings) -> None:
    settings.set(SETTINGS_KEY, value.model_dump_json(by_alias=True))
