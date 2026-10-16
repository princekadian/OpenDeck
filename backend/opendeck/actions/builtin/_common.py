"""Helpers shared by built-in actions."""

from __future__ import annotations

import asyncio
import ntpath
from collections.abc import Callable
from typing import Any, TypeVar

from ...native.windows import shell
from ...native.windows.session import PlatformError
from ..base import ActionContext, ActionError

T = TypeVar("T")

# Editor widget hints carried in the JSON schema (see frontend ActionFields).
EXE = {"widget": "exe"}
APP = {"widget": "app"}
FILE = {"widget": "file"}
FOLDER = {"widget": "folder"}
URL = {"widget": "url"}
MULTILINE = {"widget": "multiline"}
CODE = {"widget": "code"}
AUDIO_OUTPUT = {"widget": "audio-output"}
AUDIO_INPUT = {"widget": "audio-input"}
DISPLAY = {"widget": "display"}
PAGE = {"widget": "page"}
PROFILE = {"widget": "profile"}
HOTKEY = {"widget": "hotkey"}
KEY = {"widget": "key"}
KEY_COMBO = {"widget": "key-combo"}
STEPS = {"widget": "steps"}
SUB_ACTION = {"widget": "action"}


def unit(suffix: str, **extra: Any) -> dict[str, Any]:
    return {"unit": suffix, **extra}


def windows_path(value: str) -> str:
    value = value.strip().strip('"')
    if not value:
        raise ValueError("Choose a path.")
    if not ntpath.isabs(value):
        raise ValueError("Use a full path, for example C:\\Folder\\Name.")
    return ntpath.normpath(value)


def program_path(value: str) -> str:
    value = windows_path(value)
    if not value.lower().endswith((".exe", ".lnk", ".bat", ".cmd")):
        raise ValueError("Choose a program (.exe) or a shortcut (.lnk).")
    return value


async def native(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking Windows call off the event loop, mapping failures to ActionError."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except PlatformError as exc:  # ShellError and SoundError carry their own code
        raise ActionError(getattr(exc, "code", "PLATFORM_ERROR"), str(exc)) from exc


async def open_target(target: str, *, parameters: str | None = None, directory: str | None = None) -> None:
    await native(shell.shell_open, target, parameters=parameters, directory=directory)


def runtime(ctx: ActionContext):
    if ctx.runtime is None:
        raise ActionError("NOT_AVAILABLE", "This action needs the running app.")
    return ctx.runtime


def service(ctx: ActionContext, name: str) -> Any:
    svc = runtime(ctx).services.get(name)
    if svc is None:
        raise ActionError("NOT_AVAILABLE", f"The {name} service is not available.")
    return svc
