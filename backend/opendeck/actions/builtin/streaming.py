"""OBS Studio actions (obs-websocket v5 via integrations/obs.py).

State comes from OBS events, so keys show Live / REC / the active scene without
polling. When OBS is not connected, keys say so and presses return a clear error.
"""

from __future__ import annotations

from pydantic import Field

from ...integrations.obs import ObsError, ObsIntegration
from ...services.state import ButtonState
from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome, EmptyConfig
from ._common import service

OBS_SCENE = {"widget": "obs-scene"}
OBS_AUDIO_INPUT = {"widget": "obs-audio-input"}


def _source(kind: str) -> dict:
    # The source list depends on the chosen scene (field "scene"; empty = current scene).
    return {"widget": "obs-source", "sceneField": "scene", "sourceKind": kind}


class SceneConfig(ActionConfig):
    scene: str = Field(title="Scene", min_length=1, max_length=256, json_schema_extra=OBS_SCENE)


class SourceConfig(ActionConfig):
    scene: str = Field(default="", title="Scene", max_length=256, json_schema_extra=OBS_SCENE,
                       description="Leave empty to use whatever scene is live.")
    source: str = Field(title="Source", min_length=1, max_length=256, json_schema_extra=_source("all"))


class CameraConfig(SourceConfig):
    source: str = Field(title="Camera source", min_length=1, max_length=256, json_schema_extra=_source("video"))


class InputConfig(ActionConfig):
    input: str = Field(title="Audio source", min_length=1, max_length=256, json_schema_extra=OBS_AUDIO_INPUT,
                       description="An OBS audio input, such as Mic/Aux.")


def _obs(ctx: ActionContext) -> ObsIntegration:
    return service(ctx, "obs")


async def _call(coro):
    try:
        return await coro
    except ObsError as exc:
        raise ActionError(exc.code, exc.message) from exc


OFFLINE = ButtonState("obs-offline", {"text": "OBS offline"})


class _ObsAction(Action):
    category = "streaming"
    icon = "broadcast"
    stateful = True  # refreshed from OBS events, never polled

    async def read_state(self, config, ctx: ActionContext) -> ButtonState | None:
        obs = _obs(ctx)
        if not obs.connected:
            return OFFLINE
        try:
            return await self.obs_state(config, obs)
        except ObsError:
            return ButtonState("obs-error", {"text": "Not found", "tone": "error"})

    async def obs_state(self, config, obs: ObsIntegration) -> ButtonState | None:
        return None


def _stream_state(obs: ObsIntegration) -> ButtonState:
    if obs.state.streaming:
        return ButtonState("live", {"text": "Live", "tone": "error", "live": True})
    return ButtonState("offline", {"text": "Not live", "live": False})


def _record_state(obs: ObsIntegration) -> ButtonState:
    if obs.state.recording and obs.state.record_paused:
        return ButtonState("paused", {"text": "Paused", "tone": "busy", "icon": "pause"})
    if obs.state.recording:
        return ButtonState("recording", {"text": "REC", "tone": "error", "recording": True})
    return ButtonState("idle", {"text": "Not recording", "recording": False})


class ObsStartStreaming(_ObsAction):
    type = "obs_start_streaming"
    display_name = "OBS: Start streaming"
    description = "Go live with OBS's current stream settings."
    config_model = EmptyConfig

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        await _call(_obs(ctx).request("StartStream"))
        return ActionOutcome(message="Going live")

    async def obs_state(self, config, obs):
        return _stream_state(obs)


class ObsStopStreaming(_ObsAction):
    type = "obs_stop_streaming"
    display_name = "OBS: Stop streaming"
    description = "End the stream."
    config_model = EmptyConfig

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        await _call(_obs(ctx).request("StopStream"))
        return ActionOutcome(message="Stream ended")

    async def obs_state(self, config, obs):
        return _stream_state(obs)


class ObsStartRecording(_ObsAction):
    type = "obs_start_recording"
    display_name = "OBS: Start recording"
    description = "Start recording to OBS's recording folder."
    icon = "record"
    config_model = EmptyConfig

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        await _call(_obs(ctx).request("StartRecord"))
        return ActionOutcome(message="Recording")

    async def obs_state(self, config, obs):
        return _record_state(obs)


class ObsStopRecording(_ObsAction):
    type = "obs_stop_recording"
    display_name = "OBS: Stop recording"
    description = "Stop recording and save the file."
    icon = "record"
    config_model = EmptyConfig

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        data = await _call(_obs(ctx).request("StopRecord"))
        return ActionOutcome(message="Saved", data={"path": data.get("outputPath", "")})

    async def obs_state(self, config, obs):
        return _record_state(obs)


class ObsPauseRecording(_ObsAction):
    type = "obs_pause_recording"
    display_name = "OBS: Pause recording"
    description = "Pause the recording, or resume it if paused."
    icon = "pause"
    config_model = EmptyConfig

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        obs = _obs(ctx)
        if obs.connected and not obs.state.recording:
            raise ActionError("OBS_NOT_ACTIVE", "OBS is not recording.")
        await _call(obs.request("ToggleRecordPause"))
        return ActionOutcome(message="Resumed" if obs.state.record_paused else "Paused")

    async def obs_state(self, config, obs):
        return _record_state(obs)


class ObsChangeScene(_ObsAction):
    type = "obs_change_scene"
    display_name = "OBS: Change scene"
    description = "Switch OBS to a scene. The key lights up while that scene is live."
    icon = "monitor"
    config_model = SceneConfig

    async def execute(self, config: SceneConfig, ctx: ActionContext) -> ActionOutcome:
        await _call(_obs(ctx).request("SetCurrentProgramScene", {"sceneName": config.scene}))
        return ActionOutcome(message=config.scene)

    async def obs_state(self, config: SceneConfig, obs):
        if obs.state.program_scene == config.scene:
            return ButtonState("active", {"text": "Live scene", "tone": "online", "active": True})
        return ButtonState("inactive", {"active": False})


class ObsToggleSource(_ObsAction):
    type = "obs_toggle_source"
    display_name = "OBS: Toggle source"
    description = "Show or hide a source in a scene."
    icon = "window"
    config_model = SourceConfig
    on_text, off_text = "Visible", "Hidden"

    async def execute(self, config: SourceConfig, ctx: ActionContext) -> ActionOutcome:
        visible = await _call(_obs(ctx).toggle_scene_item(config.scene, config.source))
        return ActionOutcome(message=self.on_text if visible else self.off_text, data={"visible": visible})

    async def obs_state(self, config: SourceConfig, obs):
        _item, enabled = await obs.scene_item(config.scene, config.source)
        if enabled:
            return ButtonState("on", {"text": self.on_text, "tone": "online", "visible": True})
        return ButtonState("off", {"text": self.off_text, "visible": False})


class ObsToggleCamera(ObsToggleSource):
    type = "obs_toggle_camera"
    display_name = "OBS: Toggle camera"
    description = "Show or hide a camera (video capture) source in a scene."
    icon = "camera"
    config_model = CameraConfig
    on_text, off_text = "Camera on", "Camera off"


class ObsToggleMicrophone(_ObsAction):
    type = "obs_toggle_microphone"
    display_name = "OBS: Toggle microphone"
    description = "Mute or unmute an OBS audio source."
    icon = "mic"
    config_model = InputConfig

    async def execute(self, config: InputConfig, ctx: ActionContext) -> ActionOutcome:
        obs = _obs(ctx)
        data = await _call(obs.request("ToggleInputMute", {"inputName": config.input}))
        muted = bool(data.get("inputMuted"))
        obs.state.input_muted[config.input] = muted
        return ActionOutcome(message="Muted" if muted else "Live", data={"muted": muted})

    async def obs_state(self, config: InputConfig, obs):
        if await obs.input_muted(config.input):
            return ButtonState("muted", {"text": "Muted", "icon": "mic-off", "tone": "error", "muted": True})
        return ButtonState("live", {"text": "Live", "icon": "mic", "tone": "online", "muted": False})


OBS_ACTION_TYPES = {cls.type for cls in (ObsStartStreaming, ObsStopStreaming, ObsStartRecording, ObsStopRecording,
                                         ObsPauseRecording, ObsChangeScene, ObsToggleSource, ObsToggleCamera,
                                         ObsToggleMicrophone)}
