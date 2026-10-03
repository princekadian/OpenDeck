"""Audio service: the only place actions talk to for volume, mute and devices.

Wraps the Windows Core Audio layer so a different implementation (or another
OS) can be swapped in without touching actions. All COM work happens on one
dedicated worker thread, as Core Audio objects are thread-affine.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeVar

log = logging.getLogger(__name__)

Flow = Literal["output", "input"]
T = TypeVar("T")

# Windows shows its volume pop-up only for volume keys it handles itself. For the default
# speakers we tap the key, wait (at most this long) for Windows to apply it, then set the
# exact level. If the key never takes effect, the exact level is still set.
FLYOUT_WAIT_S = 0.4
FLYOUT_POLL_S = 0.02


class AudioServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AudioLevel:
    volume: int  # 0..100
    muted: bool


class AudioService:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio",
                                            initializer=self._init_thread)

    @staticmethod
    def _init_thread() -> None:
        from ..native.windows import com

        com.init_thread()

    async def _call(self, fn: Callable[..., T], *args: Any) -> T:
        from ..native.windows import audio
        from ..native.windows.com import ComError
        from ..native.windows.session import PlatformError

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(self._executor, fn, *args)
        except audio.AudioError as exc:
            raise AudioServiceError(exc.code, exc.message) from exc
        except (ComError, PlatformError) as exc:
            log.warning("Audio call %s failed: %s", getattr(fn, "__name__", fn), exc)
            raise AudioServiceError("AUDIO_FAILED", "Windows could not change the audio setting.") from exc

    async def devices(self, flow: Flow) -> list[dict[str, Any]]:
        from ..native.windows import audio

        found = await self._call(audio.list_devices, flow)
        return [{"id": d.id, "name": d.name, "isDefault": d.is_default} for d in found]

    async def level(self, flow: Flow, device_id: str | None = None) -> AudioLevel:
        from ..native.windows import audio

        volume, muted = await self._call(audio.get_level, flow, device_id)
        return AudioLevel(round(volume * 100), muted)

    async def set_volume(self, flow: Flow, percent: int, device_id: str | None = None) -> AudioLevel:
        from ..native.windows import audio

        percent = max(0, min(100, percent))
        if _has_flyout(flow, device_id):
            current = await self.level(flow, device_id)
            up = percent >= current.volume
            # At the limit the key changes nothing, but Windows still shows the pop-up.
            moves = current.muted or (current.volume < 100 if up else current.volume > 0)
            await self._tap_and_wait("VOLUME_UP" if up else "VOLUME_DOWN", flow, current if moves else None)
        await self._call(audio.set_level, flow, percent / 100, device_id)
        return await self.level(flow, device_id)

    async def change_volume(self, flow: Flow, delta: int, device_id: str | None = None) -> AudioLevel:
        current = await self.level(flow, device_id)
        return await self.set_volume(flow, current.volume + delta, device_id)

    async def set_mute(self, flow: Flow, muted: bool | None, device_id: str | None = None) -> AudioLevel:
        """muted=None toggles."""
        from ..native.windows import audio

        current = await self.level(flow, device_id)
        if muted is None:
            muted = not current.muted
        if _has_flyout(flow, device_id) and muted != current.muted:
            # The mute key toggles and shows the pop-up; fall back to Core Audio if it didn't apply.
            await self._tap_and_wait("VOLUME_MUTE", flow, current)
            if (await self.level(flow, device_id)).muted == muted:
                return await self.level(flow, device_id)
        await self._call(audio.set_mute, flow, muted, device_id)
        return await self.level(flow, device_id)

    async def _tap_and_wait(self, key: str, flow: Flow, before: AudioLevel | None) -> None:
        """Tap a volume key; if `before` is given, wait until Windows has changed the level."""
        from ..native.windows import keyboard

        try:
            await self._call(keyboard.tap_key, key)
        except AudioServiceError:
            return  # the pop-up is a nicety; the level is still set exactly afterwards
        if before is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + FLYOUT_WAIT_S
        while loop.time() < deadline:
            if await self.level(flow) != before:
                return
            await asyncio.sleep(FLYOUT_POLL_S)

    async def set_default(self, device_id: str) -> None:
        from ..native.windows import audio

        await self._call(audio.set_default_device, device_id)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _has_flyout(flow: Flow, device_id: str | None) -> bool:
    """Windows' volume keys (and their pop-up) act on the default speakers only."""
    return flow == "output" and not device_id
