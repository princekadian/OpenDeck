"""Windows session control via Win32 (user32.LockWorkStation)."""

from __future__ import annotations

import ctypes
import sys


class PlatformError(RuntimeError):
    """A Win32 call failed or the platform is unsupported."""


def _require_windows() -> None:
    if sys.platform != "win32":
        raise PlatformError("This action requires Windows.")


def lock_workstation() -> None:
    """Lock the interactive session. Returns once the lock request is accepted."""
    _require_windows()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if not user32.LockWorkStation():
        code = ctypes.get_last_error()
        raise PlatformError(f"LockWorkStation failed (Win32 error {code}).")
