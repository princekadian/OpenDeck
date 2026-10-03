"""WebSocket hub: authenticates devices, dispatches messages, broadcasts state."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from ..actions import ActionEngine, ActionError
from ..models import Device
from ..protocol import (
    PROTOCOL_VERSION, ActionExecutePayload, CloseCode, Envelope, ErrorInfo, HelloPayload,
    MessageType, MonitorSubscribePayload, error_message, message,
)
from ..services.pairing import PairingService
from ..services.snapshot import SnapshotService
from ..services.state import ButtonState

log = logging.getLogger(__name__)

HELLO_TIMEOUT_SECONDS = 5.0
# Reordering by drag or editing in quick succession produces one update, not many.
CONFIG_BROADCAST_DELAY_SECONDS = 0.05


@dataclass(eq=False)
class Session:
    id: str
    websocket: WebSocket
    device: Device
    remote: str
    user_agent: str = ""
    connected_at: float = 0.0
    # Showing a System Monitoring page right now.
    monitoring: bool = False
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _tasks: set[asyncio.Task] = field(default_factory=set)

    async def send(self, data: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.websocket.send_text(json.dumps(data, separators=(",", ":")))

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def cancel_tasks(self) -> None:
        for task in self._tasks:
            task.cancel()


class ConnectionHub:
    def __init__(
        self,
        *,
        server_name: str,
        pairing: PairingService,
        engine: ActionEngine,
        snapshots: SnapshotService,
        on_seen: Callable[[str], None] | None = None,
        on_monitor_subscribe: Callable[[Session], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._server_name = server_name
        self._pairing = pairing
        self._engine = engine
        self._snapshots = snapshots
        self._on_seen = on_seen
        self.on_monitor_subscribe = on_monitor_subscribe
        self._sessions: dict[str, Session] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._broadcast_pending = False
        self._background: set[asyncio.Task] = set()

    # ---- public API -----------------------------------------------------

    def connected_devices(self) -> list[dict[str, Any]]:
        return [
            {"sessionId": s.id, "deviceId": s.device.id, "deviceName": s.device.name,
             "remote": s.remote, "userAgent": s.user_agent, "connectedAt": s.connected_at}
            for s in self._sessions.values()
        ]

    def rename_device(self, device_id: str, name: str) -> None:
        for session in self._sessions.values():
            if session.device.id == device_id:
                session.device = session.device.model_copy(update={"name": name})

    async def broadcast(self, data: dict[str, Any], *, exclude: Session | None = None) -> None:
        targets = [s for s in self._sessions.values() if s is not exclude]
        results = await asyncio.gather(*(s.send(data) for s in targets), return_exceptions=True)
        for session, result in zip(targets, results):
            if isinstance(result, Exception):
                log.debug("Broadcast to %s failed: %s", session.id, result)

    async def on_button_state(self, button_id: str, state: ButtonState | None) -> None:
        wire = state.to_wire() if state else {"state": None, "detail": {}}
        await self.broadcast(message(MessageType.BUTTON_STATE, {"buttonId": button_id, **wire}))

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def has_sessions(self) -> bool:
        return bool(self._sessions)

    def monitor_watchers(self) -> int:
        return sum(1 for s in self._sessions.values() if s.monitoring)

    async def publish_monitor(self, payload: dict[str, Any]) -> None:
        """One reading, sent only to devices showing a monitoring page."""
        data = message(MessageType.SYSTEM_MONITOR, payload)
        targets = [s for s in self._sessions.values() if s.monitoring]
        results = await asyncio.gather(*(s.send(data) for s in targets), return_exceptions=True)
        for session, result in zip(targets, results):
            if isinstance(result, Exception):
                log.debug("Monitoring update to %s failed: %s", session.id, result)

    async def navigate(self, session_id: str | None, command: dict[str, Any]) -> bool:
        """Tell one device session to change its view (Go to page / profile / back)."""
        session = self._sessions.get(session_id or "")
        if session is None:
            return False
        await session.send(message(MessageType.NAVIGATE, command))
        return True

    async def notify_config_changed(self) -> None:
        await self.broadcast(message(MessageType.SNAPSHOT, self._snapshots.build()))

    def schedule(self, coroutine_fn: Callable[[], Coroutine[Any, Any, Any]]) -> Callable[[], None]:
        """Adapter: a sync callback that runs `coroutine_fn` on the hub's loop (if running)."""

        def trigger() -> None:
            loop = self._loop
            if loop is None:
                return

            def start() -> None:
                task = loop.create_task(coroutine_fn())
                self._background.add(task)
                task.add_done_callback(self._background.discard)

            loop.call_soon_threadsafe(start)

        return trigger

    def schedule_config_broadcast(self) -> None:
        """Push the new configuration to all devices, coalescing bursts of edits.

        Safe to call from any thread: the broadcast always runs on the loop that
        owns the device sessions. No session has connected yet means nobody to notify.
        """
        loop = self._loop
        if loop is None:
            return
        try:
            on_hub_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_hub_loop = False
        if not on_hub_loop:
            loop.call_soon_threadsafe(self.schedule_config_broadcast)
            return
        if self._broadcast_pending:
            return
        self._broadcast_pending = True

        def flush() -> None:
            self._broadcast_pending = False
            task = loop.create_task(self.notify_config_changed())
            self._background.add(task)
            task.add_done_callback(self._background.discard)

        loop.call_later(CONFIG_BROADCAST_DELAY_SECONDS, flush)

    async def disconnect_device(self, device_id: str) -> None:
        for session in [s for s in self._sessions.values() if s.device.id == device_id]:
            await _close(session.websocket, CloseCode.DEVICE_REVOKED)

    # ---- connection lifecycle ---------------------------------------------

    async def handle(self, websocket: WebSocket) -> None:
        self._loop = asyncio.get_running_loop()
        await websocket.accept()
        remote = websocket.client.host if websocket.client else "unknown"
        device = await self._handshake(websocket)
        if device is None:
            return
        session = Session(id=uuid.uuid4().hex[:12], websocket=websocket, device=device,
                          user_agent=websocket.headers.get("user-agent", "")[:300], connected_at=time.time(),
                          remote=remote)
        self._sessions[session.id] = session
        log.info("Device connected: %s (%s) from %s, %s", device.name, device.id, remote,
                 websocket.headers.get("user-agent", "unknown client")[:200])
        if self._on_seen:
            self._on_seen(device.id)
        close_code: int | None = None
        try:
            await session.send(message(MessageType.WELCOME, {
                "deviceId": device.id,
                "deviceName": device.name,
                "serverName": self._server_name,
                "protocolVersion": PROTOCOL_VERSION,
            }))
            await session.send(message(MessageType.SNAPSHOT, self._snapshots.build()))
            await self.broadcast(
                message(MessageType.DEVICE_CONNECTED,
                        {"deviceId": device.id, "deviceName": device.name}),
                exclude=session,
            )
            await self._receive_loop(session)
        except WebSocketDisconnect as exc:
            close_code = exc.code
        except Exception:
            log.exception("WebSocket session %s crashed", session.id)
        finally:
            session.cancel_tasks()
            self._sessions.pop(session.id, None)
            log.info("Device disconnected: %s (%s), close code %s", device.name, device.id,
                     close_code)
            await self.broadcast(message(MessageType.DEVICE_DISCONNECTED,
                                         {"deviceId": device.id, "deviceName": device.name}))

    async def _handshake(self, websocket: WebSocket) -> Device | None:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), HELLO_TIMEOUT_SECONDS)
            envelope = Envelope.model_validate_json(raw)
        except (asyncio.TimeoutError, ValidationError, ValueError, KeyError, WebSocketDisconnect):
            await _close(websocket, CloseCode.AUTH_REQUIRED)
            return None
        if envelope.version != PROTOCOL_VERSION:
            await _send_and_close(websocket, error_message(
                "unsupported_version", f"Server speaks protocol v{PROTOCOL_VERSION}."),
                CloseCode.UNSUPPORTED_VERSION)
            return None
        if envelope.type != MessageType.HELLO:
            await _close(websocket, CloseCode.AUTH_REQUIRED)
            return None
        try:
            hello = HelloPayload.model_validate(envelope.payload)
        except ValidationError:
            await _close(websocket, CloseCode.AUTH_FAILED)
            return None
        device = self._pairing.authenticate(hello.token)
        if device is None:
            log.warning("Rejected WebSocket with unknown or revoked token")
            await _send_and_close(websocket, error_message("auth_failed", "Device is not paired."),
                                  CloseCode.AUTH_FAILED)
            return None
        return device

    async def _receive_loop(self, session: Session) -> None:
        while True:
            raw = await session.websocket.receive_text()
            try:
                envelope = Envelope.model_validate_json(raw)
            except (ValidationError, ValueError):
                await session.send(error_message("bad_message", "Malformed message."))
                continue
            await self._dispatch(session, envelope)

    async def _dispatch(self, session: Session, envelope: Envelope) -> None:
        if envelope.type == MessageType.PING:
            await session.send(message(MessageType.PONG, request_id=envelope.request_id))
        elif envelope.type == MessageType.ACTION_EXECUTE:
            try:
                payload = ActionExecutePayload.model_validate(envelope.payload)
            except ValidationError:
                await session.send(error_message(
                    "bad_payload", "Invalid ACTION_EXECUTE payload.",
                    request_id=envelope.request_id))
                return
            # Run concurrently so a slow action never blocks pings or other buttons.
            session.spawn(self._execute(session, payload.button_id, envelope.request_id,
                                        payload.confirmed))
        elif envelope.type == MessageType.MONITOR_SUBSCRIBE:
            try:
                sub = MonitorSubscribePayload.model_validate(envelope.payload)
            except ValidationError:
                await session.send(error_message(
                    "bad_payload", "Invalid MONITOR_SUBSCRIBE payload.", request_id=envelope.request_id))
                return
            session.monitoring = sub.active
            if sub.active and self.on_monitor_subscribe:
                await self.on_monitor_subscribe(session)
        else:
            await session.send(error_message(
                "unknown_type", f"Unknown message type '{envelope.type}'.",
                request_id=envelope.request_id))

    async def _execute(self, session: Session, button_id: str, request_id: str | None,
                       confirmed: bool) -> None:
        result: dict[str, Any] = {"buttonId": button_id}
        try:
            outcome = await self._engine.execute_button(button_id, session.device.id,
                                                        session_id=session.id, confirmed=confirmed)
        except ActionError as exc:
            reply = message(MessageType.ACTION_RESULT, result, request_id=request_id,
                            success=False, error=ErrorInfo(code=exc.code, message=exc.message))
        else:
            result.update(message=outcome.message, data=outcome.data)
            reply = message(MessageType.ACTION_RESULT, result, request_id=request_id,
                            success=True)
        try:
            await session.send(reply)
        except Exception:
            log.debug("Could not deliver ACTION_RESULT to %s", session.id)


async def _send_and_close(websocket: WebSocket, data: dict[str, Any], code: int) -> None:
    try:
        await websocket.send_text(json.dumps(data))
    except Exception:
        pass
    await _close(websocket, code)


async def _close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code)
    except Exception:
        pass
