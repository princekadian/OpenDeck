"""Services an executing action may use, provided by the application at startup.

Keeps actions independent of the web server and database: they get a narrow
interface instead of the whole app.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .base import ActionContext, ActionOutcome


class RuntimeStore(Protocol):
    """Persistent key/value state for toggles, counters and timers."""

    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any]) -> None: ...


@dataclass
class ActionRuntime:
    store: RuntimeStore
    # Run another registered action (Multi Action steps, Toggle branches).
    run_step: Callable[[str, dict[str, Any], ActionContext], Awaitable[ActionOutcome]]
    # Send a navigation command to the device session that pressed the button.
    navigate: Callable[[str | None, dict[str, Any]], Awaitable[bool]]
    # Re-read and publish state for every button using any of these action types.
    refresh_state: Callable[[set[str]], Awaitable[None]]
    # Shared services for action implementations (e.g. "audio").
    services: dict[str, Any]
