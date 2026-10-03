"""Resolves a button to its stored action and executes it safely."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from ..repositories import ButtonRepository
from .base import ActionContext, ActionError, ActionOutcome, ActionStatus
from .registry import ActionRegistry
from .runtime import ActionRuntime

log = logging.getLogger(__name__)

MAX_STEP_DEPTH = 3


class ActionEngine:
    def __init__(self, registry: ActionRegistry, buttons: ButtonRepository) -> None:
        self._registry = registry
        self._buttons = buttons
        self.runtime: ActionRuntime | None = None

    async def execute_button(self, button_id: str, device_id: str | None, *,
                             session_id: str | None = None, confirmed: bool = False) -> ActionOutcome:
        """Execute the action stored for `button_id`. Raises ActionError on failure.

        The client only supplies the button id (and whether the user confirmed);
        type and configuration always come from the server-side database.
        """
        button = self._buttons.get(button_id)
        if button is None:
            raise ActionError("UNKNOWN_BUTTON", "This button no longer exists.")
        if not button.enabled:
            raise ActionError("BUTTON_DISABLED", "This button is disabled.")
        if button.kind != "action":
            # Folders only navigate, on the device. They never run anything on the PC.
            raise ActionError("NOT_AN_ACTION", "This is a folder. Devices open it themselves.")
        ctx = ActionContext(button_id=button_id, device_id=device_id, session_id=session_id,
                            runtime=self.runtime)
        return await self._run(button.action_type, button.action_config, ctx, confirmed=confirmed)

    async def execute_draft(self, action_type: str, raw_config: dict[str, Any]) -> ActionOutcome:
        """Run an unsaved action from the PC-side editor's Test button (loopback only)."""
        ctx = ActionContext(button_id="draft", device_id=None, runtime=self.runtime)
        return await self._run(action_type, raw_config, ctx, confirmed=True)

    async def run_step(self, action_type: str, raw_config: dict[str, Any], parent: ActionContext) -> ActionOutcome:
        """Run a nested action (Multi Action step, Toggle branch) with the parent's context."""
        if parent.depth >= MAX_STEP_DEPTH:
            raise ActionError("TOO_DEEP", "Actions are nested too deeply.")
        return await self._run(action_type, raw_config, replace(parent, depth=parent.depth + 1), confirmed=True)

    async def _run(self, action_type: str, raw_config: dict[str, Any], ctx: ActionContext, *,
                   confirmed: bool) -> ActionOutcome:
        action = self._registry.get(action_type)
        if action is None:
            raise ActionError("UNKNOWN_ACTION", f"Unsupported action type '{action_type}'.")
        if action.status != ActionStatus.AVAILABLE:
            raise ActionError("NOT_AVAILABLE", f"{action.display_name} is not available yet.")
        try:
            config = action.parse_config(raw_config)
        except ValidationError as exc:
            log.warning("Invalid config for button %s: %s", ctx.button_id, exc.errors())
            raise ActionError("INVALID_CONFIG",
                              "This button's settings are invalid. Edit it on the PC.") from exc
        if action.requires_confirmation(config) and not confirmed:
            raise ActionError("CONFIRMATION_REQUIRED", "Tap again to confirm.")

        started = time.perf_counter()
        try:
            outcome = await action.execute(config, ctx)
        except ActionError as exc:
            log.warning("Action %s (button %s) failed: %s %s", action.type, ctx.button_id,
                        exc.code, exc.message)
            raise
        except Exception as exc:
            log.exception("Action %s (button %s) crashed", action.type, ctx.button_id)
            raise ActionError("ACTION_FAILED", "The action failed. Details are in the PC log.") from exc
        log.info(
            "Action %s (button %s, device %s) ok in %.0f ms",
            action.type, ctx.button_id, ctx.device_id, (time.perf_counter() - started) * 1000,
        )
        if action.stateful and ctx.depth == 0 and self.runtime is not None:
            # Reflect the effect on the key right away instead of waiting for the next poll.
            await self.runtime.refresh_state({action.type})
        return outcome
