"""System actions: lock, power, sign out, Task Manager, Settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...native.windows import power, session
from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome, EmptyConfig
from ._common import native, open_target


class ConfirmConfig(ActionConfig):
    confirm: bool = Field(default=True, title="Ask for a second tap on the device",
                          description="Prevents an accidental tap from turning the PC off.")


class LockWindowsAction(Action[EmptyConfig]):
    type = "lock_windows"
    display_name = "Lock Windows"
    description = "Lock the PC and show the Windows sign-in screen."
    category = "system"
    icon = "lock"

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        await native(session.lock_workstation)
        return ActionOutcome(message="Windows locked")


class _PowerAction(Action[ConfirmConfig]):
    category = "system"
    config_model = ConfirmConfig
    destructive = True

    def requires_confirmation(self, config: ConfirmConfig) -> bool:
        return config.confirm


class ShutdownAction(_PowerAction):
    type = "shutdown"
    display_name = "Shutdown"
    description = "Shut down the PC. Apps get the usual chance to save or cancel."
    icon = "power"

    async def execute(self, config: ConfirmConfig, ctx: ActionContext) -> ActionOutcome:
        await native(power.shutdown)
        return ActionOutcome(message="Shutting down")


class RestartAction(_PowerAction):
    type = "restart"
    display_name = "Restart"
    description = "Restart the PC."
    icon = "restart"

    async def execute(self, config: ConfirmConfig, ctx: ActionContext) -> ActionOutcome:
        await native(power.restart)
        return ActionOutcome(message="Restarting")


class SleepAction(_PowerAction):
    type = "sleep"
    display_name = "Sleep"
    description = "Put the PC to sleep."
    icon = "moon"

    async def execute(self, config: ConfirmConfig, ctx: ActionContext) -> ActionOutcome:
        await native(power.sleep)
        return ActionOutcome(message="Going to sleep")


class HibernateAction(_PowerAction):
    type = "hibernate"
    display_name = "Hibernate"
    description = "Save the session to disk and power off. Requires hibernation to be enabled."
    icon = "moon"

    async def execute(self, config: ConfirmConfig, ctx: ActionContext) -> ActionOutcome:
        if not await native(power.hibernate_available):
            raise ActionError("HIBERNATE_UNAVAILABLE",
                              "Hibernate is turned off on this PC. Enable it with 'powercfg /hibernate on'.")
        await native(power.hibernate)
        return ActionOutcome(message="Hibernating")


class SignOutAction(_PowerAction):
    type = "sign_out"
    display_name = "Sign out"
    description = "Sign out of Windows. Unsaved work in open apps may be lost."
    icon = "sign-out"

    async def execute(self, config: ConfirmConfig, ctx: ActionContext) -> ActionOutcome:
        await native(power.sign_out)
        return ActionOutcome(message="Signing out")


class TaskManagerAction(Action[EmptyConfig]):
    type = "task_manager"
    display_name = "Open Task Manager"
    description = "Open Windows Task Manager."
    category = "system"
    icon = "activity"

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        await open_target("taskmgr.exe")
        return ActionOutcome(message="Opened")


SETTINGS_PAGES = {
    "home": ("Home", "ms-settings:"),
    "display": ("Display", "ms-settings:display"),
    "sound": ("Sound", "ms-settings:sound"),
    "bluetooth": ("Bluetooth & devices", "ms-settings:bluetooth"),
    "network": ("Network & internet", "ms-settings:network"),
    "personalization": ("Personalization", "ms-settings:personalization"),
    "apps": ("Apps", "ms-settings:appsfeatures"),
    "power": ("Power & battery", "ms-settings:powersleep"),
    "storage": ("Storage", "ms-settings:storagesense"),
    "update": ("Windows Update", "ms-settings:windowsupdate"),
    "privacy": ("Privacy & security", "ms-settings:privacy"),
}

SettingsPage = Literal["home", "display", "sound", "bluetooth", "network", "personalization", "apps",
                       "power", "storage", "update", "privacy"]


class SettingsConfig(ActionConfig):
    page: SettingsPage = Field(default="home", title="Page",
                               json_schema_extra={"labels": {k: v[0] for k, v in SETTINGS_PAGES.items()}})


class OpenSettingsAction(Action[SettingsConfig]):
    type = "open_settings"
    display_name = "Open Settings"
    description = "Open Windows Settings, optionally on a specific page."
    category = "system"
    icon = "settings"
    config_model = SettingsConfig

    async def execute(self, config: SettingsConfig, ctx: ActionContext) -> ActionOutcome:
        await open_target(SETTINGS_PAGES[config.page][1])
        return ActionOutcome(message="Opened")
