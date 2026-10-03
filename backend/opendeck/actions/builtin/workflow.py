"""Workflow actions: Multi Action, Delay, Toggle, Counter, Timer.

Composite actions run their steps through the same registry and engine as
ordinary buttons (runtime.run_step), so there is a single action system.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from ...services.state import ButtonState
from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome, ActionStatus
from ._common import STEPS, SUB_ACTION, runtime, unit

# Composite actions cannot be nested inside other composites.
COMPOSITE_TYPES = {"multi_action", "toggle"}
MAX_DEPTH = 2


class Step(ActionConfig):
    # No docstring: model docstrings become help text in the editor.
    action_type: str = Field(max_length=64)
    action_config: dict[str, Any] = Field(default_factory=dict)


def _validate_step(step: Step, info: ValidationInfo, where: str) -> Step:
    registry = (info.context or {}).get("registry")
    if registry is None:  # validated without registry (e.g. reading stored config)
        return step
    action = registry.get(step.action_type)
    if action is None or action.status != ActionStatus.AVAILABLE:
        raise PydanticCustomError("step", "{where}: choose an available action.", {"where": where})
    if step.action_type in COMPOSITE_TYPES:
        raise PydanticCustomError("step", "{where}: Multi Action and Toggle can't be nested.",
                                  {"where": where})
    try:
        parsed = action.parse_config(step.action_config)
    except Exception as exc:  # pydantic ValidationError
        first = getattr(exc, "errors", lambda: [{"msg": str(exc)}])()[0]
        message = str(first.get("msg", "invalid settings")).removeprefix("Value error, ")
        raise PydanticCustomError("step", "{where} ({name}): {message}",
                                  {"where": where, "name": action.display_name, "message": message})
    return Step(action_type=step.action_type,
                action_config=parsed.model_dump(mode="json", by_alias=True, exclude_none=True))


class _CompositeAction(Action):
    """Validates nested steps against the registry it was registered in."""

    def bind(self, registry: Any) -> None:
        self._registry = registry

    def parse_config(self, raw: dict[str, Any]):
        return self.config_model.model_validate(raw, context={"registry": self._registry})


# ---- Multi Action --------------------------------------------------------------

class MultiActionConfig(ActionConfig):
    steps: list[Step] = Field(min_length=1, max_length=30, title="Actions", json_schema_extra=STEPS)
    stop_on_error: bool = Field(default=True, title="Stop if a step fails")

    @field_validator("steps")
    @classmethod
    def _steps(cls, steps: list[Step], info: ValidationInfo) -> list[Step]:
        return [_validate_step(s, info, f"Step {i + 1}") for i, s in enumerate(steps)]


class MultiAction(_CompositeAction):
    type = "multi_action"
    display_name = "Multi Action"
    description = "Run several actions in order, for example open apps, wait, then press a shortcut."
    category = "workflow"
    icon = "workflow"
    config_model = MultiActionConfig

    async def execute(self, config: MultiActionConfig, ctx: ActionContext) -> ActionOutcome:
        if ctx.depth >= MAX_DEPTH:
            raise ActionError("TOO_DEEP", "Multi Actions can't run other Multi Actions.")
        failures: list[str] = []
        for index, step in enumerate(config.steps, start=1):
            try:
                await runtime(ctx).run_step(step.action_type, step.action_config, ctx)
            except ActionError as exc:
                name = getattr(self._registry.get(step.action_type), "display_name", step.action_type)
                if config.stop_on_error:
                    raise ActionError(exc.code, f"Step {index} ({name}): {exc.message}") from exc
                failures.append(f"step {index}")
        if failures:
            return ActionOutcome(message=f"Done with errors in {', '.join(failures)}", data={"failed": failures})
        return ActionOutcome(message=f"{len(config.steps)} actions done")


class DelayConfig(ActionConfig):
    milliseconds: int = Field(default=500, ge=0, le=60_000, title="Delay", json_schema_extra=unit("ms"))


class DelayAction(Action[DelayConfig]):
    type = "delay"
    display_name = "Delay"
    description = "Wait before the next step. Use it inside a Multi Action."
    category = "workflow"
    icon = "clock"
    config_model = DelayConfig

    async def execute(self, config: DelayConfig, ctx: ActionContext) -> ActionOutcome:
        await asyncio.sleep(config.milliseconds / 1000)
        return ActionOutcome(message=f"Waited {config.milliseconds} ms")


# ---- Toggle --------------------------------------------------------------------

class ToggleConfig(ActionConfig):
    on_action: Step = Field(title="When turned on", json_schema_extra=SUB_ACTION)
    off_action: Step = Field(title="When turned off", json_schema_extra=SUB_ACTION)
    on_label: str = Field(default="On", max_length=20, title="Label when on")
    off_label: str = Field(default="Off", max_length=20, title="Label when off")

    @field_validator("on_action", "off_action")
    @classmethod
    def _branch(cls, step: Step, info: ValidationInfo) -> Step:
        return _validate_step(step, info, "When turned on" if info.field_name == "on_action" else "When turned off")


class ToggleAction(_CompositeAction):
    type = "toggle"
    display_name = "Toggle"
    description = "Two states: the first press runs one action and turns on, the next runs another and turns off."
    category = "workflow"
    icon = "toggle"
    config_model = ToggleConfig
    stateful = True

    @staticmethod
    def key(ctx: ActionContext) -> str:
        return f"toggle:{ctx.button_id}"

    async def execute(self, config: ToggleConfig, ctx: ActionContext) -> ActionOutcome:
        rt = runtime(ctx)
        is_on = bool((rt.store.get(self.key(ctx)) or {}).get("on"))
        branch = config.off_action if is_on else config.on_action
        await rt.run_step(branch.action_type, branch.action_config, ctx)  # state flips only on success
        rt.store.set(self.key(ctx), {"on": not is_on})
        await rt.refresh_state({self.type})
        label = config.off_label if is_on else config.on_label
        return ActionOutcome(message=label, data={"on": not is_on})

    async def read_state(self, config: ToggleConfig, ctx: ActionContext) -> ButtonState | None:
        on = bool((runtime(ctx).store.get(self.key(ctx)) or {}).get("on"))
        if on:
            return ButtonState("on", {"text": config.on_label, "tone": "online", "on": True})
        return ButtonState("off", {"text": config.off_label, "on": False})


# ---- Counter -------------------------------------------------------------------

class CounterConfig(ActionConfig):
    name: str = Field(default="Counter", min_length=1, max_length=30, title="Counter name",
                      description="Keys using the same name share one value, e.g. separate + and − keys.")
    operation: Literal["increment", "decrement", "reset"] = Field(
        default="increment", title="On press",
        json_schema_extra={"labels": {"increment": "Increase", "decrement": "Decrease", "reset": "Reset"}})
    amount: int = Field(default=1, ge=1, le=1_000_000, title="By",
                        json_schema_extra={"showWhen": {"operation": ["increment", "decrement"]}})
    initial_value: int = Field(default=0, ge=-1_000_000_000, le=1_000_000_000, title="Start / reset value")


class CounterAction(Action[CounterConfig]):
    type = "counter"
    display_name = "Counter"
    description = "Count up or down, or reset. The key shows the current value."
    category = "workflow"
    icon = "counter"
    config_model = CounterConfig
    stateful = True

    @staticmethod
    def key(config: CounterConfig) -> str:
        return f"counter:{config.name.strip().lower()}"

    def value(self, config: CounterConfig, ctx: ActionContext) -> int:
        stored = runtime(ctx).store.get(self.key(config))
        return int(stored["value"]) if stored else config.initial_value

    async def execute(self, config: CounterConfig, ctx: ActionContext) -> ActionOutcome:
        value = self.value(config, ctx)
        value = {"increment": value + config.amount, "decrement": value - config.amount,
                 "reset": config.initial_value}[config.operation]
        rt = runtime(ctx)
        rt.store.set(self.key(config), {"value": value})
        await rt.refresh_state({self.type})
        return ActionOutcome(message=str(value), data={"value": value})

    async def read_state(self, config: CounterConfig, ctx: ActionContext) -> ButtonState | None:
        value = self.value(config, ctx)
        return ButtonState("value", {"text": str(value), "value": value})


# ---- Timer ---------------------------------------------------------------------

class TimerConfig(ActionConfig):
    name: str = Field(default="Timer", min_length=1, max_length=30, title="Timer name",
                      description="Keys using the same name control one timer, e.g. a separate Reset key.")
    minutes: float = Field(default=5, ge=0.1, le=1440, title="Duration", json_schema_extra=unit("min"))
    operation: Literal["start_pause", "reset"] = Field(
        default="start_pause", title="On press",
        json_schema_extra={"labels": {"start_pause": "Start / pause", "reset": "Reset"}})


def _now_ms() -> int:
    return int(time.time() * 1000)


class TimerAction(Action[TimerConfig]):
    """Countdown kept on the PC. Devices animate the remaining time themselves from one
    state update, so nothing is sent every second."""

    type = "timer"
    display_name = "Timer"
    description = "Countdown timer. The key shows the remaining time."
    category = "workflow"
    icon = "timer"
    config_model = TimerConfig
    stateful = True

    def __init__(self) -> None:
        self._alarms: dict[str, asyncio.TimerHandle] = {}

    @staticmethod
    def key(config: TimerConfig) -> str:
        return f"timer:{config.name.strip().lower()}"

    def _state(self, config: TimerConfig, ctx: ActionContext) -> dict[str, Any]:
        duration = int(config.minutes * 60_000)
        stored = runtime(ctx).store.get(self.key(config))
        if not stored or stored.get("durationMs") != duration:
            return {"durationMs": duration, "remainingMs": duration, "runningSince": None}
        return stored

    @staticmethod
    def _remaining(state: dict[str, Any]) -> int:
        if state["runningSince"] is None:
            return state["remainingMs"]
        return max(0, state["remainingMs"] - (_now_ms() - state["runningSince"]))

    async def execute(self, config: TimerConfig, ctx: ActionContext) -> ActionOutcome:
        rt = runtime(ctx)
        state = self._state(config, ctx)
        remaining = self._remaining(state)
        key = self.key(config)
        if config.operation == "reset" or remaining == 0:
            state = {"durationMs": state["durationMs"], "remainingMs": state["durationMs"], "runningSince": None}
            if config.operation == "start_pause":  # pressing a finished timer starts it again
                state["runningSince"] = _now_ms()
        elif state["runningSince"] is None:
            state = {**state, "remainingMs": remaining, "runningSince": _now_ms()}
        else:
            state = {**state, "remainingMs": remaining, "runningSince": None}
        rt.store.set(key, state)
        self._schedule(key, state, rt)
        await rt.refresh_state({self.type})
        running = state["runningSince"] is not None
        return ActionOutcome(message="Started" if running else ("Reset" if config.operation == "reset" else "Paused"))

    def _schedule(self, key: str, state: dict[str, Any], rt) -> None:
        if (handle := self._alarms.pop(key, None)) is not None:
            handle.cancel()
        if state["runningSince"] is None:
            return
        loop = asyncio.get_running_loop()
        delay = self._remaining(state) / 1000
        # One wake-up when the countdown ends, to show "Done" on every device.
        self._alarms[key] = loop.call_later(delay, lambda: loop.create_task(rt.refresh_state({self.type})))

    async def read_state(self, config: TimerConfig, ctx: ActionContext) -> ButtonState | None:
        state = self._state(config, ctx)
        remaining = self._remaining(state)
        running = state["runningSince"] is not None
        if running and remaining == 0:
            return ButtonState("finished", {"text": "Done", "tone": "online", "countdown": {
                "remainingMs": 0, "running": False}})
        detail: dict[str, Any] = {"countdown": {"remainingMs": remaining, "running": running}}
        if running:
            detail["tone"] = "busy"
            # Distinct per start so devices restart their local countdown.
            return ButtonState(f"running:{state['runningSince']}", detail)
        if remaining < state["durationMs"]:
            detail["text"] = "Paused"
        return ButtonState("paused" if remaining < state["durationMs"] else "idle", detail)
