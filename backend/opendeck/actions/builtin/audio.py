"""Audio actions on Windows Core Audio (via the AudioService), with live button state."""

from __future__ import annotations

from pydantic import Field

from ...services.audio import AudioLevel, AudioService, AudioServiceError
from ...services.state import ButtonState
from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome
from ._common import AUDIO_INPUT, AUDIO_OUTPUT, service, unit


class OutputDevice(ActionConfig):
    device_id: str = Field(default="", title="Device", max_length=512, json_schema_extra=AUDIO_OUTPUT,
                           description="Leave as the default output to follow Windows.")


class InputDevice(ActionConfig):
    device_id: str = Field(default="", title="Device", max_length=512, json_schema_extra=AUDIO_INPUT,
                           description="Leave as the default microphone to follow Windows.")


class OutputStep(OutputDevice):
    amount: int = Field(default=5, ge=1, le=100, title="Amount", json_schema_extra=unit("%"))


class InputStep(InputDevice):
    amount: int = Field(default=5, ge=1, le=100, title="Amount", json_schema_extra=unit("%"))


class SetOutputVolume(OutputDevice):
    volume: int = Field(default=50, ge=0, le=100, title="Volume", json_schema_extra=unit("%"))


class OutputDeviceChoice(ActionConfig):
    device_id: str = Field(title="Device", min_length=1, max_length=512, json_schema_extra=AUDIO_OUTPUT)


class InputDeviceChoice(ActionConfig):
    device_id: str = Field(title="Device", min_length=1, max_length=512, json_schema_extra=AUDIO_INPUT)


def _audio(ctx: ActionContext) -> AudioService:
    return service(ctx, "audio")


async def _do(coro):
    try:
        return await coro
    except AudioServiceError as exc:
        raise ActionError(exc.code, exc.message) from exc


def _volume_state(level: AudioLevel, *, mic: bool = False) -> ButtonState:
    if level.muted:
        return ButtonState("muted", {"text": "Muted", "icon": "mic-off" if mic else "volume-off",
                                     "tone": "error", "value": level.volume, "muted": True})
    return ButtonState("level", {"text": f"{level.volume}%", "value": level.volume, "muted": False})


class _OutputLevelAction(Action):
    """Shows the device's current volume on the key."""

    category = "audio"
    stateful = True
    polled = True
    flow = "output"

    async def read_state(self, config, ctx: ActionContext) -> ButtonState | None:
        level = await _do(_audio(ctx).level(self.flow, config.device_id or None))
        return _volume_state(level, mic=self.flow == "input")

    def outcome(self, level: AudioLevel) -> ActionOutcome:
        text = "Muted" if level.muted else f"{level.volume}%"
        return ActionOutcome(message=text, data={"volume": level.volume, "muted": level.muted})


class VolumeUpAction(_OutputLevelAction):
    type = "volume_up"
    display_name = "Volume up"
    description = "Raise the volume of the default (or chosen) speakers."
    icon = "volume-up"
    config_model = OutputStep

    async def execute(self, config: OutputStep, ctx: ActionContext) -> ActionOutcome:
        return self.outcome(await _do(_audio(ctx).change_volume("output", config.amount, config.device_id or None)))


class VolumeDownAction(_OutputLevelAction):
    type = "volume_down"
    display_name = "Volume down"
    description = "Lower the volume of the default (or chosen) speakers."
    icon = "volume-down"
    config_model = OutputStep

    async def execute(self, config: OutputStep, ctx: ActionContext) -> ActionOutcome:
        return self.outcome(await _do(_audio(ctx).change_volume("output", -config.amount, config.device_id or None)))


class SetVolumeAction(_OutputLevelAction):
    type = "set_volume"
    display_name = "Set volume"
    description = "Set the speaker volume to an exact level."
    icon = "volume"
    config_model = SetOutputVolume

    async def execute(self, config: SetOutputVolume, ctx: ActionContext) -> ActionOutcome:
        return self.outcome(await _do(_audio(ctx).set_volume("output", config.volume, config.device_id or None)))


class MuteToggleAction(_OutputLevelAction):
    type = "mute_toggle"
    display_name = "Mute / unmute"
    description = "Mute or unmute the speakers. The key shows the current state."
    icon = "volume-off"
    config_model = OutputDevice

    async def execute(self, config: OutputDevice, ctx: ActionContext) -> ActionOutcome:
        return self.outcome(await _do(_audio(ctx).set_mute("output", None, config.device_id or None)))


class MicUpAction(_OutputLevelAction):
    type = "mic_volume_up"
    display_name = "Increase microphone volume"
    description = "Raise the microphone input level."
    icon = "mic"
    flow = "input"
    config_model = InputStep

    async def execute(self, config: InputStep, ctx: ActionContext) -> ActionOutcome:
        return self.outcome(await _do(_audio(ctx).change_volume("input", config.amount, config.device_id or None)))


class MicDownAction(_OutputLevelAction):
    type = "mic_volume_down"
    display_name = "Decrease microphone volume"
    description = "Lower the microphone input level."
    icon = "mic"
    flow = "input"
    config_model = InputStep

    async def execute(self, config: InputStep, ctx: ActionContext) -> ActionOutcome:
        return self.outcome(await _do(_audio(ctx).change_volume("input", -config.amount, config.device_id or None)))


class MicMuteAction(_OutputLevelAction):
    type = "mic_mute"
    display_name = "Mute microphone"
    description = "Mute or unmute the microphone. The key shows Mic on / Mic muted."
    icon = "mic-off"
    flow = "input"
    config_model = InputDevice

    async def execute(self, config: InputDevice, ctx: ActionContext) -> ActionOutcome:
        level = await _do(_audio(ctx).set_mute("input", None, config.device_id or None))
        return ActionOutcome(message="Mic muted" if level.muted else "Mic on", data={"muted": level.muted})

    async def read_state(self, config: InputDevice, ctx: ActionContext) -> ButtonState | None:
        level = await _do(_audio(ctx).level("input", config.device_id or None))
        if level.muted:
            return ButtonState("muted", {"text": "Mic muted", "icon": "mic-off", "tone": "error", "muted": True})
        return ButtonState("live", {"text": "Mic on", "icon": "mic", "tone": "online", "muted": False})


class _DefaultDeviceAction(Action):
    category = "audio"
    stateful = True
    polled = True
    flow = "output"

    async def execute(self, config, ctx: ActionContext) -> ActionOutcome:
        audio = _audio(ctx)
        devices = await _do(audio.devices(self.flow))
        match = next((d for d in devices if d["id"] == config.device_id), None)
        if match is None:
            raise ActionError("DEVICE_NOT_FOUND", "The selected audio device is not connected.")
        await _do(audio.set_default(config.device_id))
        return ActionOutcome(message=f"Using {match['name']}")

    async def read_state(self, config, ctx: ActionContext) -> ButtonState | None:
        devices = await _do(_audio(ctx).devices(self.flow))
        current = next((d for d in devices if d["isDefault"]), None)
        active = current is not None and current["id"] == config.device_id
        return ButtonState("active" if active else "inactive", {"tone": "online" if active else None,
                                                                "text": "In use" if active else ""})


class OutputDeviceAction(_DefaultDeviceAction):
    type = "audio_output_device"
    display_name = "Change audio output device"
    description = "Make a playback device the Windows default."
    icon = "speaker"
    config_model = OutputDeviceChoice


class InputDeviceAction(_DefaultDeviceAction):
    type = "audio_input_device"
    display_name = "Change microphone device"
    description = "Make a recording device the Windows default."
    icon = "mic"
    flow = "input"
    config_model = InputDeviceChoice


# Media menu entries for volume reuse the audio executors.

class MediaVolumeUpAction(VolumeUpAction):
    type = "media_volume_up"
    category = "media"


class MediaVolumeDownAction(VolumeDownAction):
    type = "media_volume_down"
    category = "media"
