"""Start with Windows: one value under HKCU\\...\\CurrentVersion\\Run.

This is the standard, per-user, reversible mechanism (it is what Task Manager's
Startup tab lists and lets users disable). Only the packaged app registers itself:
a development checkout has no stable executable to point at.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ...branding import PRODUCT_NAME

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = PRODUCT_NAME


def executable() -> Path | None:
    """The installed OpenDeck.exe, or None when running from source."""
    return Path(sys.executable) if getattr(sys, "frozen", False) else None


def command() -> str | None:
    exe = executable()
    # --minimized: start in the notification area without opening the window.
    return f'"{exe}" --minimized' if exe else None


def is_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            cmd = command()
            if cmd is None:
                raise RuntimeError("Start with Windows is available in the installed app.")
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
