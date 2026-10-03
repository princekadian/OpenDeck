"""OBS connection settings in the settings table. The password is encrypted with
Windows DPAPI for the current user and never sent back to the editor."""

from __future__ import annotations

import base64
import logging

from ..integrations.obs import ObsSettings
from ..repositories import SettingsRepository

log = logging.getLogger(__name__)

_KEYS = {"enabled": "obs.enabled", "host": "obs.host", "port": "obs.port", "password": "obs.password_dpapi"}


def _protect(password: str) -> str:
    from ..native.windows import dpapi

    return base64.b64encode(dpapi.protect(password.encode("utf-8"))).decode()


def _unprotect(stored: str) -> str:
    from ..native.windows import dpapi

    try:
        return dpapi.unprotect(base64.b64decode(stored)).decode("utf-8")
    except Exception:
        log.warning("Stored OBS password could not be decrypted (different Windows user?)")
        return ""


def load_obs_settings(settings: SettingsRepository) -> ObsSettings:
    stored = settings.get(_KEYS["password"])
    return ObsSettings(
        enabled=settings.get(_KEYS["enabled"]) == "1",
        host=settings.get(_KEYS["host"]) or "127.0.0.1",
        port=int(settings.get(_KEYS["port"]) or 4455),
        password=_unprotect(stored) if stored else "",
    )


def save_obs_settings(settings: SettingsRepository, value: ObsSettings) -> None:
    settings.set(_KEYS["enabled"], "1" if value.enabled else "0")
    settings.set(_KEYS["host"], value.host)
    settings.set(_KEYS["port"], str(value.port))
    settings.set(_KEYS["password"], _protect(value.password) if value.password else "")
