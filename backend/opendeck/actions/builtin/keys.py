"""Keyboard and media-key actions (SendInput)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator

from ...native.windows import keyboard
from ..base import Action, ActionConfig, ActionContext, ActionOutcome, EmptyConfig
from ._common import HOTKEY, KEY, KEY_COMBO, MULTILINE, native

Modifier = Literal["CTRL", "ALT", "SHIFT", "WIN"]


def _key_name(value: str) -> str:
    value = value.strip().upper()
    if value not in keyboard.KEYS:
        raise ValueError("Choose a key.")
    return value


KeyName = Annotated[str, AfterValidator(_key_name)]


# Stored structurally, e.g. {"modifiers": ["CTRL", "SHIFT"], "key": "S"}.
# (A docstring here would be shown to users as help text by the editor.)
class Shortcut(ActionConfig):
    modifiers: list[Modifier] = Field(default_factory=list, max_length=4)
    key: KeyName

    @field_validator("modifiers")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return [m for m in keyboard.MODIFIER_ORDER if m in value]

    def display(self) -> str:
        names = {"CTRL": "Ctrl", "ALT": "Alt", "SHIFT": "Shift", "WIN": "Win"}
        return " + ".join([*(names[m] for m in self.modifiers), self.key.replace("_", " ").title()])


class HotkeyConfig(ActionConfig):
    shortcut: Shortcut = Field(title="Shortcut", json_schema_extra=HOTKEY)


class KeyComboConfig(ActionConfig):
    combination: Shortcut = Field(title="Key combination", json_schema_extra=KEY_COMBO)


class KeyPressConfig(ActionConfig):
    key: KeyName = Field(title="Key", json_schema_extra=KEY)


class TypeTextConfig(ActionConfig):
    text: str = Field(title="Text", min_length=1, max_length=5000, json_schema_extra=MULTILINE,
                      description="Typed into the app that is active on the PC. New lines press Enter.")


class HotkeyAction(Action[HotkeyConfig]):
    type = "hotkey"
    display_name = "Hotkey"
    description = "Press a recorded keyboard shortcut on the PC."
    category = "keyboard"
    icon = "keyboard"
    config_model = HotkeyConfig

    async def execute(self, config: HotkeyConfig, ctx: ActionContext) -> ActionOutcome:
        await native(keyboard.press_combo, config.shortcut.modifiers, config.shortcut.key)
        return ActionOutcome(message=config.shortcut.display())


class TypeTextAction(Action[TypeTextConfig]):
    type = "type_text"
    display_name = "Type text"
    description = "Type text into the active app on the PC. Works with any language and emoji."
    category = "keyboard"
    icon = "text"
    config_model = TypeTextConfig

    async def execute(self, config: TypeTextConfig, ctx: ActionContext) -> ActionOutcome:
        await native(keyboard.type_text, config.text)
        return ActionOutcome(message="Typed")


class KeyPressAction(Action[KeyPressConfig]):
    type = "key_press"
    display_name = "Key press"
    description = "Press a single key, such as F13, Enter or Media play/pause."
    category = "keyboard"
    icon = "keyboard"
    config_model = KeyPressConfig

    async def execute(self, config: KeyPressConfig, ctx: ActionContext) -> ActionOutcome:
        await native(keyboard.press_combo, [], config.key)
        return ActionOutcome(message="Pressed")


class KeyComboAction(Action[KeyComboConfig]):
    type = "key_combination"
    display_name = "Key combination"
    description = "Press modifier keys together with a key, chosen from lists."
    category = "keyboard"
    icon = "keyboard"
    config_model = KeyComboConfig

    async def execute(self, config: KeyComboConfig, ctx: ActionContext) -> ActionOutcome:
        await native(keyboard.press_combo, config.combination.modifiers, config.combination.key)
        return ActionOutcome(message=config.combination.display())


class _MediaKeyAction(Action[EmptyConfig]):
    """Windows routes media keys to the active media session (any app using System Media
    Transport Controls: Spotify, browsers, Media Player…), so nothing is app-specific."""

    category = "media"
    key = ""

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        await native(keyboard.press_combo, [], self.key)
        return ActionOutcome(message="Sent")


class PlayPauseAction(_MediaKeyAction):
    type = "media_play_pause"
    display_name = "Play / Pause"
    description = "Play or pause whatever is playing on the PC."
    icon = "play-pause"
    key = "MEDIA_PLAY_PAUSE"


class PreviousTrackAction(_MediaKeyAction):
    type = "media_previous"
    display_name = "Previous track"
    description = "Go to the previous track."
    icon = "previous"
    key = "MEDIA_PREVIOUS"


class NextTrackAction(_MediaKeyAction):
    type = "media_next"
    display_name = "Next track"
    description = "Skip to the next track."
    icon = "next"
    key = "MEDIA_NEXT"


class StopMediaAction(_MediaKeyAction):
    type = "media_stop"
    display_name = "Stop"
    description = "Stop playback."
    icon = "stop"
    key = "MEDIA_STOP"
