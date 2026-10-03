"""Versioned WebSocket protocol. Mirrored in frontend/src/protocol/messages.ts.

See docs/PROTOCOL.md for the full specification.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

PROTOCOL_VERSION = 2


class MessageType(StrEnum):
    # client -> server
    HELLO = "HELLO"
    ACTION_EXECUTE = "ACTION_EXECUTE"
    MONITOR_SUBSCRIBE = "MONITOR_SUBSCRIBE"
    PING = "PING"
    # server -> client
    WELCOME = "WELCOME"
    SNAPSHOT = "SNAPSHOT"
    ACTION_RESULT = "ACTION_RESULT"
    BUTTON_STATE = "BUTTON_STATE"
    NAVIGATE = "NAVIGATE"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    DEVICE_CONNECTED = "DEVICE_CONNECTED"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    SYSTEM_MONITOR = "SYSTEM_MONITOR"
    PONG = "PONG"
    ERROR = "ERROR"


class CloseCode:
    AUTH_REQUIRED = 4001
    UNSUPPORTED_VERSION = 4002
    AUTH_FAILED = 4003
    DEVICE_REVOKED = 4004


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class ErrorInfo(_Wire):
    code: str
    message: str


class Envelope(_Wire):
    version: int = PROTOCOL_VERSION
    type: str
    request_id: str | None = Field(default=None, max_length=64)
    success: bool | None = None
    error: ErrorInfo | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class HelloPayload(_Wire):
    token: str = Field(min_length=16, max_length=128)
    client_version: str | None = Field(default=None, max_length=32)


class ActionExecutePayload(_Wire):
    button_id: str = Field(min_length=1, max_length=64)
    # Second tap on a key that asks for confirmation (Shut down, Restart…).
    confirmed: bool = False


class MonitorSubscribePayload(_Wire):
    # True while a monitoring page is on screen; the PC only samples while someone watches.
    active: bool


def message(
    type_: MessageType,
    payload: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
    success: bool | None = None,
    error: ErrorInfo | None = None,
) -> dict[str, Any]:
    return Envelope(
        type=type_, payload=payload or {}, request_id=request_id, success=success, error=error
    ).to_wire()


def error_message(code: str, text: str, *, request_id: str | None = None) -> dict[str, Any]:
    return message(
        MessageType.ERROR, request_id=request_id, success=False,
        error=ErrorInfo(code=code, message=text),
    )
