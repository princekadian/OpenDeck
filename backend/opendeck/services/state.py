"""In-memory button state store; changes are pushed to devices as BUTTON_STATE.

ButtonState.detail is a small, generic display vocabulary that the dashboard
renders for any action (no per-action UI):
  text       short status line ("62%", "Muted", "Running")
  icon       built-in icon name overriding the key's icon ("volume-off")
  tone       LED colour: "online" | "busy" | "error"
  countdown  {"remainingMs": int, "running": bool}; the device animates it locally
Other keys (value, muted, running, on) are data for future use.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

StateListener = Callable[[str, "ButtonState | None"], Awaitable[None]]


@dataclass(frozen=True)
class ButtonState:
    state: str
    detail: dict[str, Any] | None = None

    def to_wire(self) -> dict[str, Any]:
        return {"state": self.state, "detail": {k: v for k, v in (self.detail or {}).items() if v is not None}}


class StateManager:
    def __init__(self) -> None:
        self._states: dict[str, ButtonState] = {}
        self._listeners: list[StateListener] = []

    def subscribe(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {bid: s.to_wire() for bid, s in self._states.items()}

    def get(self, button_id: str) -> ButtonState | None:
        return self._states.get(button_id)

    async def set(self, button_id: str, state: ButtonState | None) -> None:
        """Store state (None clears it) and notify listeners only when it actually changed."""
        if self._states.get(button_id) == state:
            return
        if state is None:
            self._states.pop(button_id, None)
        else:
            self._states[button_id] = state
        for listener in self._listeners:
            await listener(button_id, state)

    def prune(self, valid_ids: set[str]) -> None:
        """Forget state of deleted buttons (no broadcast: devices get a new snapshot anyway)."""
        for button_id in [b for b in self._states if b not in valid_ids]:
            del self._states[button_id]
