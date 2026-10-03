"""Display actions: brightness, projection mode, HDR."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...native.windows import display
from ...services.state import ButtonState
from ..base import Action, ActionConfig, ActionContext, ActionOutcome
from ._common import DISPLAY, native, unit


class DisplayChoice(ActionConfig):
    display_id: str = Field(default="", title="Display", max_length=64, json_schema_extra=DISPLAY,
                            description="Leave as the primary display or choose another.")


class BrightnessStep(DisplayChoice):
    amount: int = Field(default=10, ge=1, le=100, title="Amount", json_schema_extra=unit("%"))


class SetBrightnessConfig(DisplayChoice):
    brightness: int = Field(default=50, ge=0, le=100, title="Brightness", json_schema_extra=unit("%"))


class ProjectionConfig(ActionConfig):
    mode: Literal["internal", "clone", "extend", "external"] = Field(
        default="extend", title="Show on",
        json_schema_extra={"labels": {"internal": "PC screen only", "clone": "Duplicate",
                                      "extend": "Extend", "external": "Second screen only"}})


def _brightness_state(value: int) -> ButtonState:
    return ButtonState("level", {"text": f"{value}%", "value": value})


class _BrightnessAction(Action):
    category = "display"
    icon = "sun"
    stateful = True

    async def read_state(self, config, ctx: ActionContext) -> ButtonState | None:
        try:
            return _brightness_state(await native(display.get_brightness, config.display_id))
        except Exception:
            return None  # unsupported display: show the key without a level


class BrightnessUpAction(_BrightnessAction):
    type = "brightness_up"
    display_name = "Brightness up"
    description = "Raise screen brightness (laptop panels, and monitors with DDC/CI enabled)."
    config_model = BrightnessStep

    async def execute(self, config: BrightnessStep, ctx: ActionContext) -> ActionOutcome:
        current = await native(display.get_brightness, config.display_id)
        value = await native(display.set_brightness, current + config.amount, config.display_id)
        return ActionOutcome(message=f"{value}%", data={"brightness": value})


class BrightnessDownAction(_BrightnessAction):
    type = "brightness_down"
    display_name = "Brightness down"
    description = "Lower screen brightness."
    config_model = BrightnessStep

    async def execute(self, config: BrightnessStep, ctx: ActionContext) -> ActionOutcome:
        current = await native(display.get_brightness, config.display_id)
        value = await native(display.set_brightness, current - config.amount, config.display_id)
        return ActionOutcome(message=f"{value}%", data={"brightness": value})


class SetBrightnessAction(_BrightnessAction):
    type = "set_brightness"
    display_name = "Set brightness"
    description = "Set screen brightness to an exact level."
    config_model = SetBrightnessConfig

    async def execute(self, config: SetBrightnessConfig, ctx: ActionContext) -> ActionOutcome:
        value = await native(display.set_brightness, config.brightness, config.display_id)
        return ActionOutcome(message=f"{value}%", data={"brightness": value})


class ChangeDisplayAction(Action[ProjectionConfig]):
    type = "change_display"
    display_name = "Change display"
    description = "Switch between PC screen only, Duplicate, Extend and Second screen only (like Win+P)."
    category = "display"
    icon = "monitor"
    config_model = ProjectionConfig

    async def execute(self, config: ProjectionConfig, ctx: ActionContext) -> ActionOutcome:
        await native(display.set_projection, config.mode)
        return ActionOutcome(message="Switched")


class ToggleHdrAction(Action[DisplayChoice]):
    type = "toggle_hdr"
    display_name = "Toggle HDR"
    description = "Turn HDR on or off for a display that supports it."
    category = "display"
    icon = "hdr"
    config_model = DisplayChoice
    stateful = True

    async def execute(self, config: DisplayChoice, ctx: ActionContext) -> ActionOutcome:
        _supported, enabled = await native(display.hdr_state, config.display_id)
        await native(display.set_hdr, not enabled, config.display_id)
        return ActionOutcome(message="HDR on" if not enabled else "HDR off", data={"hdr": not enabled})

    async def read_state(self, config: DisplayChoice, ctx: ActionContext) -> ButtonState | None:
        try:
            supported, enabled = await native(display.hdr_state, config.display_id)
        except Exception:
            return None
        if not supported:
            return ButtonState("unsupported", {"text": "No HDR"})
        return ButtonState("on" if enabled else "off", {"text": "HDR on" if enabled else "HDR off",
                                                         "tone": "online" if enabled else None})
