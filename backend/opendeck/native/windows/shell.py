"""Open applications, documents, folders and URLs through the Windows shell.

ShellExecuteW is used instead of subprocess because it:
- honours file associations (documents, folders, the default browser),
- shows the UAC prompt for apps that require elevation (subprocess fails with 740),
- does not tie the launched program's lifetime or console to this process.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .session import PlatformError, _require_windows

SW_SHOWNORMAL = 1
ASFW_ANY = -1
COINIT_APARTMENTTHREADED = 0x2
COINIT_DISABLE_OLE1DDE = 0x4


class ShellError(PlatformError):
    """ShellExecute failed. `code` is a stable, user-facing error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ShellExecuteW returns a value <= 32 on failure; see the Win32 documentation.
_SHELL_ERRORS: dict[int, tuple[str, str]] = {
    0: ("OUT_OF_RESOURCES", "Windows is out of memory or resources."),
    2: ("FILE_NOT_FOUND", "The file could not be found."),
    3: ("PATH_NOT_FOUND", "The path could not be found."),
    5: ("PERMISSION_DENIED", "Windows denied access."),
    8: ("OUT_OF_RESOURCES", "Windows is out of memory."),
    11: ("INVALID_EXECUTABLE", "The file is not a valid Windows program."),
    26: ("SHARING_VIOLATION", "The file is in use by another program."),
    27: ("NO_ASSOCIATION", "No application is associated with this file type."),
    28: ("TIMEOUT", "Windows did not respond in time."),
    29: ("LAUNCH_FAILED", "Windows could not start the program."),
    30: ("BUSY", "Windows is busy. Try again."),
    31: ("NO_ASSOCIATION", "No application is associated with this file type."),
    32: ("FILE_NOT_FOUND", "A required file could not be found."),
}


def shell_open(target: str, *, parameters: str | None = None, directory: str | None = None,
               verb: str = "open") -> None:
    """Open `target` like double-clicking it in Explorer. Raises ShellError on failure."""
    _require_windows()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")
    user32 = ctypes.WinDLL("user32")

    shell32.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
    shell32.ShellExecuteW.restype = ctypes.c_void_p

    # Shell extensions may use COM; each worker thread initialises it (no-op if done).
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE)
    # We run in the background; let the launched window come to the foreground.
    user32.AllowSetForegroundWindow(ASFW_ANY)

    result = shell32.ShellExecuteW(None, verb, target, parameters or None, directory or None,
                                   SW_SHOWNORMAL) or 0
    if result > 32:
        return
    if result == 5 and ctypes.get_last_error() == 1223:  # ERROR_CANCELLED: UAC declined
        raise ShellError("CANCELLED", "The administrator prompt was declined on the PC.")
    code, message = _SHELL_ERRORS.get(result, ("LAUNCH_FAILED", f"Windows error {result}."))
    raise ShellError(code, message)
