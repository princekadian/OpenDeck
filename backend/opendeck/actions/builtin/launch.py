"""Open things on the PC: applications, URLs, files and folders."""

from __future__ import annotations

import os
import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field

from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome
from ._common import EXE, FILE, FOLDER, URL, open_target, program_path, windows_path

# "scheme:" prefix that is not a port number ("localhost:3000" is a host, not a scheme).
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)")


def web_url(value: str, schemes: tuple[str, ...] = ("http", "https")) -> str:
    value = value.strip()
    prefixes = tuple(f"{s}://" for s in schemes)
    if _SCHEME.match(value) and not value.lower().startswith(prefixes):
        raise ValueError(f"Only {' and '.join(prefixes)} addresses can be opened.")
    if value and "://" not in value:
        value = f"{schemes[-1]}://" + value
    parts = urlsplit(value)
    if parts.scheme not in schemes or not parts.netloc or " " in value:
        raise ValueError(f"Enter an address starting with {' or '.join(prefixes)}.")
    return value


ProgramPath = Annotated[str, AfterValidator(program_path)]
WindowsPath = Annotated[str, AfterValidator(windows_path)]
WebUrl = Annotated[str, AfterValidator(web_url)]


class LaunchApplicationConfig(ActionConfig):
    path: ProgramPath = Field(title="Application", max_length=1024, json_schema_extra=EXE)
    arguments: str = Field(default="", title="Arguments", max_length=1024,
                           description="Optional command-line arguments.")


class OpenUrlConfig(ActionConfig):
    url: WebUrl = Field(title="Web address", max_length=2048, json_schema_extra=URL)


class OpenFileConfig(ActionConfig):
    path: WindowsPath = Field(title="File", max_length=1024, json_schema_extra=FILE)


class OpenFolderConfig(ActionConfig):
    path: WindowsPath = Field(title="Folder", max_length=1024, json_schema_extra=FOLDER)


async def launch(path: str, arguments: str = "") -> None:
    if not os.path.isfile(path):
        raise ActionError("FILE_NOT_FOUND", "The configured application could not be found on the PC.")
    await open_target(path, parameters=arguments or None, directory=os.path.dirname(path))


class LaunchApplicationAction(Action[LaunchApplicationConfig]):
    type = "launch_application"
    display_name = "Launch application"
    description = "Start a program on the PC."
    category = "open"
    icon = "app"
    config_model = LaunchApplicationConfig

    async def execute(self, config: LaunchApplicationConfig, ctx: ActionContext) -> ActionOutcome:
        await launch(config.path, config.arguments)
        return ActionOutcome(message="Launched")


class OpenUrlAction(Action[OpenUrlConfig]):
    type = "open_url"
    display_name = "Open website"
    description = "Open a web address in the PC's default browser."
    category = "open"
    icon = "globe"
    config_model = OpenUrlConfig

    async def execute(self, config: OpenUrlConfig, ctx: ActionContext) -> ActionOutcome:
        await open_target(config.url)
        return ActionOutcome(message="Opened")


class OpenFileAction(Action[OpenFileConfig]):
    type = "open_file"
    display_name = "Open file"
    description = "Open a file with its default application."
    category = "open"
    icon = "file"
    config_model = OpenFileConfig

    async def execute(self, config: OpenFileConfig, ctx: ActionContext) -> ActionOutcome:
        if not os.path.isfile(config.path):
            raise ActionError("FILE_NOT_FOUND", "The configured file no longer exists.")
        await open_target(config.path, directory=os.path.dirname(config.path))
        return ActionOutcome(message="Opened")


class OpenFolderAction(Action[OpenFolderConfig]):
    type = "open_folder"
    display_name = "Open folder"
    description = "Show a folder in File Explorer."
    category = "open"
    icon = "folder"
    config_model = OpenFolderConfig

    async def execute(self, config: OpenFolderConfig, ctx: ActionContext) -> ActionOutcome:
        if not os.path.isdir(config.path):
            raise ActionError("FOLDER_NOT_FOUND", "The configured folder no longer exists.")
        await open_target(config.path)
        return ActionOutcome(message="Opened")


# The same executors listed again under other menu categories (own ids, shared code).

class AppLaunchAction(LaunchApplicationAction):
    type = "app_launch"
    category = "applications"


class NavOpenFolderAction(OpenFolderAction):
    type = "nav_open_folder"
    category = "navigation"


class NavOpenUrlAction(OpenUrlAction):
    type = "nav_open_url"
    display_name = "Open URL"
    category = "navigation"
