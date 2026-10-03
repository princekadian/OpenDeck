"""Device pairing: short-lived numeric codes exchanged for long-lived device tokens."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from dataclasses import dataclass

from ..models import Device
from ..repositories import DeviceRepository

log = logging.getLogger(__name__)

CODE_TTL_SECONDS = 300
MAX_FAILED_ATTEMPTS = 5


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class _PendingCode:
    code: str
    expires_at: float
    failed_attempts: int = 0


class PairingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PairingService:
    """Only one pairing code is valid at a time.

    The code is shown on the PC (localhost editor / tray). Five wrong guesses
    invalidate it, so a 6-digit code cannot be brute-forced from the LAN.
    """

    def __init__(self, devices: DeviceRepository, *, clock=time.monotonic) -> None:
        self._devices = devices
        self._clock = clock
        self._pending: _PendingCode | None = None

    def current_code(self) -> tuple[str, float]:
        """Return the active code and its remaining seconds, issuing one if needed."""
        now = self._clock()
        if self._pending is None or self._pending.expires_at <= now:
            self._pending = _PendingCode(
                code=f"{secrets.randbelow(1_000_000):06d}", expires_at=now + CODE_TTL_SECONDS
            )
            log.info("New pairing code issued")
        return self._pending.code, self._pending.expires_at - now

    def pair(self, code: str, device_name: str) -> tuple[Device, str]:
        """Validate `code`; on success create a device and return (device, raw token)."""
        pending = self._pending
        if pending is None or pending.expires_at <= self._clock():
            raise PairingError("code_expired", "No active pairing code. Show a new code on the PC.")
        if not hmac.compare_digest(pending.code, code.strip()):
            pending.failed_attempts += 1
            if pending.failed_attempts >= MAX_FAILED_ATTEMPTS:
                self._pending = None
                log.warning("Pairing code invalidated after %d failed attempts", MAX_FAILED_ATTEMPTS)
            raise PairingError("invalid_code", "Incorrect pairing code.")

        self._pending = None  # single use
        token = secrets.token_urlsafe(32)
        device = self._devices.create(str(uuid.uuid4()), device_name.strip()[:64] or "Device",
                                      hash_token(token))
        log.info("Device paired: %s (%s)", device.name, device.id)
        return device, token

    def authenticate(self, token: str) -> Device | None:
        return self._devices.find_active_by_token_hash(hash_token(token))
