"""Sound effects: play an audio file on the PC (soundboard), like Stream Deck's Soundboard.

Sounds play on the PC's speakers (and so into a stream that captures desktop audio).
"Also play on" sends the same sound to a second output, typically a virtual cable used
as the microphone in Discord or another call, so people there hear it too.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections import OrderedDict
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from ...native.windows import sound
from ...services.state import ButtonState
from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome, EmptyConfig
from ._common import AUDIO_OUTPUT, native, unit, windows_path

AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".aac", ".wma")
CACHE_BYTES = 128 * 1024 * 1024


def _sound_path(value: str) -> str:
    value = windows_path(value)
    if not value.lower().endswith(AUDIO_EXTENSIONS):
        raise ValueError("Choose an audio file (MP3, WAV, OGG, FLAC, M4A…).")
    return value


SoundPath = Annotated[str, AfterValidator(_sound_path)]


class PlaySoundConfig(ActionConfig):
    path: SoundPath = Field(title="Sound file", max_length=1024, json_schema_extra={"widget": "audio-file"})
    volume: int = Field(default=100, ge=0, le=100, title="Volume", json_schema_extra=unit("%"))
    device_id: str = Field(default="", title="Play on", max_length=512, json_schema_extra=AUDIO_OUTPUT,
                           description="Leave as the default output to follow Windows.")
    also_device_id: str = Field(
        default="", title="Also play on", max_length=512,
        json_schema_extra={**AUDIO_OUTPUT, "emptyLabel": "Nowhere else"},
        description="For voice chat: pick a virtual cable (for example CABLE Input) that Discord uses as "
                    "its microphone, so people in the call hear the sound too.")
    when_playing: Literal["stop", "restart", "overlap"] = Field(
        default="stop", title="Pressed again while playing",
        json_schema_extra={"labels": {"stop": "Stop the sound", "restart": "Play it from the start",
                                      "overlap": "Play it again on top"}})


class SoundPlayer:
    """Sounds playing right now (per button) and recently decoded files."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._playing: dict[str, list[sound.Playback]] = {}
        self._cache: OrderedDict[tuple, sound.Pcm] = OrderedDict()

    def is_playing(self, key: str) -> bool:
        with self._lock:
            return any(not p.done for p in self._playing.get(key, []))

    def stop(self, key: str | None = None) -> int:
        """Stop one button's sounds, or all of them. Returns how many were playing."""
        with self._lock:
            playbacks = [p for k, ps in self._playing.items() if key in (None, k) for p in ps if not p.done]
        for playback in playbacks:
            playback.stop()
        return len(playbacks)

    def pcm(self, path: str, volume: int) -> sound.Pcm:
        """Decoded (and volume-adjusted) sound, cached so repeated presses start at once."""
        stat = os.stat(path)
        key = (path, stat.st_mtime_ns, stat.st_size, volume)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        pcm = sound.scaled(sound.decode(path), volume)
        with self._lock:
            self._cache[key] = pcm
            while sum(len(p.data) for p in self._cache.values()) > CACHE_BYTES and len(self._cache) > 1:
                self._cache.popitem(last=False)
        return pcm

    def play(self, key: str, pcm: sound.Pcm, devices: list[str], on_end) -> None:
        playbacks = []
        try:
            for device in devices:
                playbacks.append(sound.Playback(pcm, device or None))
        except sound.SoundError:
            for playback in playbacks:
                playback.stop()
            raise
        with self._lock:
            self._playing.setdefault(key, []).extend(playbacks)

        def wait() -> None:
            for playback in playbacks:
                playback.wait()
            with self._lock:
                left = [p for p in self._playing.get(key, []) if p not in playbacks]
                if left:
                    self._playing[key] = left
                else:
                    self._playing.pop(key, None)
            on_end()

        threading.Thread(target=wait, name="sound", daemon=True).start()


player = SoundPlayer()

PLAYING = ButtonState("playing", {"text": "Playing", "tone": "online", "playing": True})


class PlaySoundAction(Action[PlaySoundConfig]):
    type = "play_sound"
    display_name = "Play sound"
    description = "Play an audio file (MP3, WAV, OGG, FLAC, M4A…) on the PC."
    category = "soundboard"
    icon = "music"
    config_model = PlaySoundConfig
    stateful = True

    async def execute(self, config: PlaySoundConfig, ctx: ActionContext) -> ActionOutcome:
        if not os.path.isfile(config.path):
            raise ActionError("FILE_NOT_FOUND", "The sound file no longer exists on the PC.")
        key = ctx.button_id
        if player.is_playing(key) and config.when_playing != "overlap":
            player.stop(key)
            if config.when_playing == "stop":
                return ActionOutcome(message="Stopped")
        pcm = await native(player.pcm, config.path, config.volume)
        devices = list(dict.fromkeys([config.device_id] + ([config.also_device_id] if config.also_device_id else [])))
        await native(player.play, key, pcm, devices, _refresh_later(ctx, self.type))
        return ActionOutcome(message="Playing", data={"seconds": round(pcm.seconds, 1)})

    async def read_state(self, config: PlaySoundConfig, ctx: ActionContext) -> ButtonState | None:
        return PLAYING if player.is_playing(ctx.button_id) else None


class StopSoundsAction(Action[EmptyConfig]):
    type = "stop_sounds"
    display_name = "Stop all sounds"
    description = "Stop every sound effect that is playing."
    category = "soundboard"
    icon = "stop"

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        return ActionOutcome(message="Stopped" if player.stop() else "Nothing playing")


def _refresh_later(ctx: ActionContext, action_type: str):
    """Called on the sound's own thread when it ends: clear "Playing" on every device."""
    rt = ctx.runtime
    if rt is None:
        return lambda: None
    loop = asyncio.get_running_loop()
    return lambda: loop.call_soon_threadsafe(lambda: loop.create_task(rt.refresh_state({action_type})))
