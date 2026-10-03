"""Keeps button state in sync with reality.

- Event-driven: after a press, a stateful action asks for a refresh of its type.
- On configuration changes: every stateful button is re-read.
- Polling, only for actions that reflect outside changes (volume, running apps),
  only while a device is connected, at a low rate, and only changes are sent.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from ..actions import ActionContext, ActionRegistry
from ..actions.runtime import ActionRuntime
from ..repositories import ButtonRepository
from .state import StateManager

log = logging.getLogger(__name__)

POLL_SECONDS = 2.0


class StateCoordinator:
    def __init__(self, registry: ActionRegistry, buttons: ButtonRepository, states: StateManager,
                 has_devices: Callable[[], bool]) -> None:
        self._registry = registry
        self._buttons = buttons
        self._states = states
        self._has_devices = has_devices
        self.runtime: ActionRuntime | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def refresh(self, action_types: set[str] | None = None, *, polled_only: bool = False) -> None:
        async with self._lock:  # one refresh at a time; COM/disk calls are not reentrant-friendly
            buttons = self._buttons.list_all()
            if action_types is None and not polled_only:
                self._states.prune({b.id for b in buttons})
            for button in buttons:
                action = self._registry.get(button.action_type) if button.kind == "action" else None
                if action is None or not action.stateful or not button.enabled:
                    if action_types is None and not polled_only:
                        await self._states.set(button.id, None)
                    continue
                if action_types is not None and button.action_type not in action_types:
                    continue
                if polled_only and not action.polled:
                    continue
                await self._states.set(button.id, await self._read(action, button))

    async def _read(self, action, button):
        try:
            config = action.parse_config(button.action_config)
            ctx = ActionContext(button_id=button.id, device_id=None, runtime=self.runtime)
            return await action.read_state(config, ctx)
        except Exception as exc:  # state is best-effort; never break the loop
            log.debug("State read failed for %s (%s): %s", button.id, button.action_type, exc)
            return None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._poll_forever())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _poll_forever(self) -> None:
        while True:
            await asyncio.sleep(POLL_SECONDS)
            if not self._has_devices():
                continue
            try:
                await self.refresh(polled_only=True)
            except Exception:
                log.exception("State polling failed")
