"""OBS Studio integration over obs-websocket v5 (built into OBS 28+).

One long-lived connection: authenticates with the server's challenge, keeps a
small mirror of OBS state up to date from events (stream/record status, program
scene, input mute, source visibility), and reconnects with backoff. Actions use
`request()` and the cached state; buttons update from events, without polling.

Protocol reference: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)

RPC_VERSION = 1
# Event subscriptions: General | Scenes | Inputs | Outputs | SceneItems.
EVENT_SUBSCRIPTIONS = 1 | 4 | 8 | 64 | 128
REQUEST_TIMEOUT = 5.0
BACKOFF = (1, 2, 5, 10, 20, 30)
CLOSE_AUTH_FAILED = 4009
CLOSE_UNSUPPORTED_RPC = 4010

# obs-websocket request status codes -> friendly messages.
_REQUEST_ERRORS = {
    500: ("OBS_ALREADY_ACTIVE", "OBS is already doing that."),
    501: ("OBS_NOT_ACTIVE", "That isn't running in OBS right now."),
    502: ("OBS_PAUSED", "The recording is paused."),
    503: ("OBS_NOT_PAUSED", "The recording is not paused."),
    600: ("OBS_NOT_FOUND", "OBS could not find that scene or source. It may have been renamed."),
    601: ("OBS_NOT_FOUND", "OBS could not find that scene or source. It may have been renamed."),
    604: ("OBS_WRONG_TYPE", "That source can't be used this way."),
}


class ObsStatus(StrEnum):
    DISABLED = "disabled"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTH_FAILED = "auth_failed"
    UNREACHABLE = "unreachable"


class ObsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ObsSettings:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"ws://{host}:{self.port}"


@dataclass
class ObsState:
    """Mirror of the OBS state that buttons show."""

    streaming: bool = False
    recording: bool = False
    record_paused: bool = False
    program_scene: str = ""
    input_muted: dict[str, bool] = field(default_factory=dict)
    # (scene, source) -> (scene item id, enabled)
    scene_items: dict[tuple[str, str], tuple[int, bool]] = field(default_factory=dict)


def auth_response(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsIntegration:
    def __init__(self, on_change: Callable[[], Awaitable[None]] | None = None) -> None:
        self._on_change = on_change
        self.settings = ObsSettings()
        self.status = ObsStatus.DISABLED
        self.message = "Turn on the OBS connection in Integrations."
        self.obs_version = ""
        self.state = ObsState()
        self._ws: Any = None
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._task: asyncio.Task | None = None
        self._notify_pending = False
        self._background: set[asyncio.Task] = set()

    # ---- lifecycle -------------------------------------------------------------

    def set_listener(self, on_change: Callable[[], Awaitable[None]]) -> None:
        self._on_change = on_change


    def configure(self, settings: ObsSettings) -> None:
        """Apply new settings; (re)connects or disconnects as needed."""
        changed = settings != self.settings
        self.settings = settings
        if not changed and self._task:
            return
        self._restart()

    def start(self) -> None:
        self._restart()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def _restart(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # not started yet; start() will run the loop
        if self._task:
            self._task.cancel()
        self._task = loop.create_task(self._run())

    @property
    def connected(self) -> bool:
        return self.status == ObsStatus.CONNECTED

    async def _set_status(self, status: ObsStatus, message: str) -> None:
        if (status, message) == (self.status, self.message):
            return
        if status != self.status:
            log.info("OBS: %s (%s)", status.value, message)
        self.status, self.message = status, message
        await self._notify()

    async def _notify(self) -> None:
        """Ask listeners to refresh, in a separate task.

        Listeners usually call request(); awaiting them from the reader would block the
        reader that must deliver those responses (deadlock until timeout). Bursts of
        events are coalesced into one refresh.
        """
        if not self._on_change or self._notify_pending:
            return
        self._notify_pending = True

        async def run() -> None:
            await asyncio.sleep(0)  # let the reader process any events queued right behind
            self._notify_pending = False
            try:
                await self._on_change()
            except Exception:
                log.exception("OBS state listener failed")

        task = asyncio.get_running_loop().create_task(run())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _run(self) -> None:
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

        attempt = 0
        while True:
            settings = self.settings
            if not settings.enabled:
                self.state = ObsState()
                await self._set_status(ObsStatus.DISABLED, "Turn on the OBS connection in Integrations.")
                return
            await self._set_status(ObsStatus.CONNECTING, f"Connecting to {settings.url}…")
            try:
                async with connect(settings.url, open_timeout=5, max_size=16 * 1024 * 1024,
                                   ping_interval=20, ping_timeout=20) as ws:
                    await self._handshake(ws, settings)
                    attempt = 0
                    self._ws = ws
                    reader = asyncio.create_task(self._read(ws))
                    try:
                        await self._sync()
                        await self._set_status(ObsStatus.CONNECTED, f"Connected to OBS {self.obs_version}".strip())
                        await reader
                    finally:
                        reader.cancel()
                        self._ws = None
                        self._fail_pending()
                await self._set_status(ObsStatus.UNREACHABLE, "OBS closed the connection.")
            except asyncio.CancelledError:
                raise
            except ObsError as exc:
                if exc.code == "OBS_AUTH_FAILED":
                    await self._set_status(ObsStatus.AUTH_FAILED, exc.message)
                    return  # retrying a wrong password is pointless; wait for new settings
                await self._set_status(ObsStatus.UNREACHABLE, exc.message)
            except ConnectionClosed as exc:
                if exc.rcvd and exc.rcvd.code == CLOSE_AUTH_FAILED:
                    await self._set_status(ObsStatus.AUTH_FAILED, "OBS rejected the password.")
                    return
                await self._set_status(ObsStatus.UNREACHABLE, "OBS closed the connection.")
            except (OSError, TimeoutError, InvalidHandshake, InvalidURI) as exc:
                await self._set_status(
                    ObsStatus.UNREACHABLE,
                    "Can't reach OBS. Is it running with the WebSocket server enabled?")
                log.debug("OBS connect failed: %s", exc)
            delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _handshake(self, ws, settings: ObsSettings) -> None:
        hello = json.loads(await asyncio.wait_for(ws.recv(), REQUEST_TIMEOUT))
        if hello.get("op") != 0:
            raise ObsError("OBS_PROTOCOL", "That address is not an OBS WebSocket server.")
        data = hello.get("d", {})
        self.obs_version = ""
        identify: dict[str, Any] = {"rpcVersion": RPC_VERSION, "eventSubscriptions": EVENT_SUBSCRIPTIONS}
        if auth := data.get("authentication"):
            if not settings.password:
                raise ObsError("OBS_AUTH_FAILED", "OBS needs a password. Enter it in Integrations.")
            identify["authentication"] = auth_response(settings.password, auth["salt"], auth["challenge"])
        await ws.send(json.dumps({"op": 1, "d": identify}))
        identified = json.loads(await asyncio.wait_for(ws.recv(), REQUEST_TIMEOUT))
        if identified.get("op") != 2:
            raise ObsError("OBS_PROTOCOL", "OBS did not accept the connection.")

    async def _read(self, ws) -> None:
        async for raw in ws:
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            op, data = message.get("op"), message.get("d", {})
            if op == 7:
                future = self._pending.pop(data.get("requestId", ""), None)
                if future and not future.done():
                    future.set_result(data)
            elif op == 5:
                await self._on_event(data.get("eventType", ""), data.get("eventData") or {})

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ObsError("OBS_DISCONNECTED", "OBS disconnected."))
        self._pending.clear()

    # ---- requests -------------------------------------------------------------------

    async def request(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        ws = self._ws
        if ws is None or not self.connected and request_type not in _SYNC_REQUESTS:
            raise ObsError("OBS_NOT_CONNECTED", self._not_connected_message())
        request_id = str(next(self._ids))
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload: dict[str, Any] = {"requestType": request_type, "requestId": request_id}
        if data:
            payload["requestData"] = data
        await ws.send(json.dumps({"op": 6, "d": payload}))
        try:
            response = await asyncio.wait_for(future, REQUEST_TIMEOUT)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise ObsError("OBS_TIMEOUT", "OBS did not answer in time.") from exc
        status = response.get("requestStatus", {})
        if not status.get("result"):
            code, message = _REQUEST_ERRORS.get(status.get("code"), ("OBS_REQUEST_FAILED", ""))
            log.warning("OBS %s failed: %s %s", request_type, status.get("code"), status.get("comment"))
            raise ObsError(code, message or f"OBS: {status.get('comment') or 'request failed'}.")
        return response.get("responseData") or {}

    def _not_connected_message(self) -> str:
        if self.status == ObsStatus.DISABLED:
            return "OBS isn't set up. Turn it on in the editor under Integrations."
        if self.status == ObsStatus.AUTH_FAILED:
            return "OBS rejected the password. Check it in Integrations."
        return "OBS is not connected. Is OBS running?"

    async def _sync(self) -> None:
        """Read the state buttons show, right after connecting."""
        self.state = ObsState()
        version = await self.request("GetVersion")
        self.obs_version = version.get("obsVersion", "")
        stream = await self.request("GetStreamStatus")
        record = await self.request("GetRecordStatus")
        scene = await self.request("GetCurrentProgramScene")
        self.state.streaming = bool(stream.get("outputActive"))
        self.state.recording = bool(record.get("outputActive"))
        self.state.record_paused = bool(record.get("outputPaused"))
        self.state.program_scene = scene.get("sceneName") or scene.get("currentProgramSceneName", "")

    # ---- events ------------------------------------------------------------------------

    async def _on_event(self, event: str, data: dict[str, Any]) -> None:
        s = self.state
        if event == "StreamStateChanged":
            s.streaming = bool(data.get("outputActive"))
        elif event == "RecordStateChanged":
            s.recording = bool(data.get("outputActive"))
            state = data.get("outputState", "")
            s.record_paused = state == "OBS_WEBSOCKET_OUTPUT_PAUSED" or (
                s.record_paused and state not in ("OBS_WEBSOCKET_OUTPUT_RESUMED", "OBS_WEBSOCKET_OUTPUT_STOPPED"))
            if not s.recording:
                s.record_paused = False
        elif event == "CurrentProgramSceneChanged":
            s.program_scene = data.get("sceneName", "")
        elif event == "InputMuteStateChanged":
            s.input_muted[data.get("inputName", "")] = bool(data.get("inputMuted"))
        elif event == "SceneItemEnableStateChanged":
            scene, item_id = data.get("sceneName", ""), data.get("sceneItemId")
            for key, (cached_id, _enabled) in list(s.scene_items.items()):
                if key[0] == scene and cached_id == item_id:
                    s.scene_items[key] = (cached_id, bool(data.get("sceneItemEnabled")))
        elif event in ("InputNameChanged", "SceneNameChanged", "SceneItemRemoved", "SceneItemCreated",
                       "InputRemoved", "SceneRemoved"):
            s.scene_items.clear()  # ids or names changed: re-read on demand
        elif event == "ExitStarted":
            await self._set_status(ObsStatus.UNREACHABLE, "OBS is closing.")
            return
        else:
            return
        await self._notify()

    # ---- helpers used by actions ------------------------------------------------------

    def resolve_scene(self, scene: str) -> str:
        return scene or self.state.program_scene

    async def input_muted(self, input_name: str) -> bool:
        if input_name not in self.state.input_muted:
            data = await self.request("GetInputMute", {"inputName": input_name})
            self.state.input_muted[input_name] = bool(data.get("inputMuted"))
        return self.state.input_muted[input_name]

    async def scene_item(self, scene: str, source: str) -> tuple[int, bool]:
        scene = self.resolve_scene(scene)
        key = (scene, source)
        if key not in self.state.scene_items:
            item = await self.request("GetSceneItemId", {"sceneName": scene, "sourceName": source})
            item_id = int(item["sceneItemId"])
            enabled = await self.request("GetSceneItemEnabled", {"sceneName": scene, "sceneItemId": item_id})
            self.state.scene_items[key] = (item_id, bool(enabled.get("sceneItemEnabled")))
        return self.state.scene_items[key]

    async def toggle_scene_item(self, scene: str, source: str) -> bool:
        scene = self.resolve_scene(scene)
        item_id, enabled = await self.scene_item(scene, source)
        await self.request("SetSceneItemEnabled", {"sceneName": scene, "sceneItemId": item_id,
                                                   "sceneItemEnabled": not enabled})
        self.state.scene_items[(scene, source)] = (item_id, not enabled)
        return not enabled

    # ---- lists for the editor -------------------------------------------------------------

    async def scenes(self) -> list[str]:
        data = await self.request("GetSceneList")
        # OBS lists scenes bottom-up; show them in the order of OBS's scene dock.
        return [s["sceneName"] for s in reversed(data.get("scenes", []))]

    async def inputs(self, kind: str = "all") -> list[str]:
        data = await self.request("GetInputList")
        inputs = data.get("inputs", [])
        if kind == "audio":
            inputs = [i for i in inputs if _is_audio(i.get("inputKind", ""))] or inputs
        elif kind == "video":
            inputs = [i for i in inputs if _is_camera(i.get("inputKind", ""))] or inputs
        return [i["inputName"] for i in inputs]

    async def scene_sources(self, scene: str) -> list[str]:
        data = await self.request("GetSceneItemList", {"sceneName": self.resolve_scene(scene)})
        return [item["sourceName"] for item in data.get("sceneItems", [])]


# Requests allowed while the connection is still being set up (before CONNECTED).
_SYNC_REQUESTS = {"GetVersion", "GetStreamStatus", "GetRecordStatus", "GetCurrentProgramScene"}


def _is_audio(kind: str) -> bool:
    return any(k in kind for k in ("wasapi", "coreaudio", "pulse", "alsa", "jack", "audio"))


def _is_camera(kind: str) -> bool:
    return any(k in kind for k in ("dshow", "av_capture", "v4l2", "video_capture"))
