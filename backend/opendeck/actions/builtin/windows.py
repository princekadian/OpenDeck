"""Window and application actions."""

from __future__ import annotations

import asyncio
import os
from typing import Annotated

from pydantic import AfterValidator, Field

from ...native.windows import keyboard, winmgmt
from ...services.state import ButtonState
from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome, EmptyConfig
from ._common import APP, native, program_path, unit
from .launch import launch

AppPath = Annotated[str, AfterValidator(program_path)]
OptionalAppPath = Annotated[str, AfterValidator(lambda v: program_path(v) if v.strip() else "")]


class AppConfig(ActionConfig):
    path: AppPath = Field(title="Application", max_length=1024, json_schema_extra=APP,
                          description="Choose from running apps or browse for the program.")


class CloseAppConfig(AppConfig):
    force: bool = Field(default=False, title="Force close if it does not respond",
                        description="Ends the app after 5 seconds. Unsaved work is lost.")


class OptionalAppConfig(ActionConfig):
    path: OptionalAppPath = Field(default="", title="Application", max_length=1024, json_schema_extra=APP,
                      description="Leave empty to switch to the previous window (like Alt+Tab).")


class MoveConfig(ActionConfig):
    x: int = Field(default=0, ge=-20000, le=20000, title="X", json_schema_extra=unit("px"))
    y: int = Field(default=0, ge=-20000, le=20000, title="Y", json_schema_extra=unit("px"))


class ResizeConfig(ActionConfig):
    width: int = Field(default=1200, ge=100, le=20000, title="Width", json_schema_extra=unit("px"))
    height: int = Field(default=800, ge=100, le=20000, title="Height", json_schema_extra=unit("px"))


async def _active() -> int:
    return await native(winmgmt.foreground_window)


class _ActiveWindowAction(Action[EmptyConfig]):
    category = "window"
    command = 0

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        await native(winmgmt.show, await _active(), self.command)
        return ActionOutcome(message="Done")


class MinimizeAction(_ActiveWindowAction):
    type = "window_minimize"
    display_name = "Minimize active window"
    description = "Minimize the window that is active on the PC."
    icon = "window-minimize"
    command = winmgmt.SW_MINIMIZE


class MaximizeAction(_ActiveWindowAction):
    type = "window_maximize"
    display_name = "Maximize active window"
    description = "Maximize the active window."
    icon = "window-maximize"
    command = winmgmt.SW_MAXIMIZE


class CloseWindowAction(Action[EmptyConfig]):
    destructive = True
    type = "window_close"
    display_name = "Close active window"
    description = "Close the active window, like clicking its X. Apps may ask to save."
    category = "window"
    icon = "window-close"

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        await native(winmgmt.close_window, await _active())
        return ActionOutcome(message="Closed")


class RestoreWindowAction(Action[EmptyConfig]):
    type = "window_restore"
    display_name = "Restore window"
    description = "Un-maximize the active window, or bring back the most recently minimized one."
    category = "window"
    icon = "window"

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        def restore() -> None:
            try:
                hwnd = winmgmt.foreground_window()
                if winmgmt.is_maximized(hwnd):
                    winmgmt.show(hwnd, winmgmt.SW_RESTORE)
                    return
            except winmgmt.PlatformError:
                pass
            minimized = [w for w in winmgmt.app_windows() if winmgmt.is_minimized(w.hwnd)]
            if not minimized:
                raise winmgmt.PlatformError("No minimized window to restore.")
            winmgmt.focus_window(minimized[0].hwnd)

        await native(restore)
        return ActionOutcome(message="Restored")


class MoveWindowAction(Action[MoveConfig]):
    type = "window_move"
    display_name = "Move window"
    description = "Move the active window so its top-left corner is at X, Y (screen pixels)."
    category = "window"
    icon = "move"
    config_model = MoveConfig

    async def execute(self, config: MoveConfig, ctx: ActionContext) -> ActionOutcome:
        await native(winmgmt.move_window, await _active(), config.x, config.y)
        return ActionOutcome(message="Moved")


class ResizeWindowAction(Action[ResizeConfig]):
    type = "window_resize"
    display_name = "Resize window"
    description = "Resize the active window."
    category = "window"
    icon = "resize"
    config_model = ResizeConfig

    async def execute(self, config: ResizeConfig, ctx: ActionContext) -> ActionOutcome:
        await native(winmgmt.resize_window, await _active(), config.width, config.height)
        return ActionOutcome(message="Resized")


async def _focus_app(path: str) -> None:
    windows = await native(winmgmt.windows_of, path)
    if not windows:
        raise ActionError("APP_NOT_RUNNING", f"{os.path.basename(path)} has no open window.")
    await native(winmgmt.focus_window, windows[0].hwnd)


class SwitchApplicationAction(Action[OptionalAppConfig]):
    type = "window_switch"
    display_name = "Switch application"
    description = "Bring an app to the front, or switch to the previous window."
    category = "window"
    icon = "switch"
    config_model = OptionalAppConfig

    async def execute(self, config: OptionalAppConfig, ctx: ActionContext) -> ActionOutcome:
        if config.path:
            await _focus_app(config.path)
        else:
            await native(keyboard.press_combo, ["ALT"], "TAB")
        return ActionOutcome(message="Switched")


class FocusApplicationAction(Action[AppConfig]):
    type = "app_focus"
    display_name = "Focus application"
    description = "Bring the app's window to the front, restoring it if minimized."
    category = "applications"
    icon = "focus"
    config_model = AppConfig

    async def execute(self, config: AppConfig, ctx: ActionContext) -> ActionOutcome:
        await _focus_app(config.path)
        return ActionOutcome(message="Focused")


async def _close_app(path: str, force: bool) -> int:
    """Ask every window of the app to close; optionally end it if it hangs. Returns closed count."""
    pids = await native(winmgmt.find_processes, path)
    if not pids:
        raise ActionError("APP_NOT_RUNNING", f"{os.path.basename(path)} is not running.")
    for window in await native(winmgmt.windows_of, path):
        await native(winmgmt.close_window, window.hwnd)
    for _ in range(25):  # up to 5 s for a graceful exit
        await asyncio.sleep(0.2)
        if not await native(winmgmt.find_processes, path):
            return len(pids)
    if force:
        for pid in await native(winmgmt.find_processes, path):
            await native(winmgmt.terminate, pid)
        return len(pids)
    raise ActionError("APP_STILL_RUNNING",
                      f"{os.path.basename(path)} did not close. It may be asking to save changes.")


class CloseApplicationAction(Action[CloseAppConfig]):
    type = "app_close"
    display_name = "Close application"
    description = "Close the app like clicking its X; optionally end it if it hangs."
    category = "applications"
    icon = "window-close"
    config_model = CloseAppConfig
    destructive = True
    stateful = True
    polled = True

    async def execute(self, config: CloseAppConfig, ctx: ActionContext) -> ActionOutcome:
        await _close_app(config.path, config.force)
        return ActionOutcome(message="Closed")

    async def read_state(self, config: CloseAppConfig, ctx: ActionContext) -> ButtonState | None:
        return await _running_state(config.path)


class RestartApplicationAction(Action[CloseAppConfig]):
    type = "app_restart"
    display_name = "Restart application"
    description = "Close the app, wait for it to exit, then start it again."
    category = "applications"
    icon = "restart"
    config_model = CloseAppConfig
    destructive = True

    async def execute(self, config: CloseAppConfig, ctx: ActionContext) -> ActionOutcome:
        try:
            await _close_app(config.path, config.force)
        except ActionError as exc:
            if exc.code != "APP_NOT_RUNNING":
                raise
        await launch(config.path)
        return ActionOutcome(message="Restarted")


async def _running_state(path: str) -> ButtonState:
    running = bool(await native(winmgmt.find_processes, path))
    return ButtonState("running" if running else "stopped",
                       {"text": "Running" if running else "Not running",
                        "tone": "online" if running else None, "running": running})


class AppRunningAction(Action[AppConfig]):
    type = "app_running"
    display_name = "Check if application is running"
    description = "Shows Running / Not running on the key. Pressing reports the current state."
    category = "applications"
    icon = "activity"
    config_model = AppConfig
    stateful = True
    polled = True

    async def execute(self, config: AppConfig, ctx: ActionContext) -> ActionOutcome:
        state = await _running_state(config.path)
        running = state.state == "running"
        return ActionOutcome(message="Running" if running else "Not running", data={"running": running})

    async def read_state(self, config: AppConfig, ctx: ActionContext) -> ButtonState | None:
        return await _running_state(config.path)
