"""Power and session control: shutdown, restart, sign out, sleep, hibernate."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .session import PlatformError, _require_windows

EWX_LOGOFF = 0x0
EWX_SHUTDOWN = 0x1
EWX_REBOOT = 0x2
EWX_POWEROFF = 0x8
EWX_FORCEIFHUNG = 0x10
# "Planned: application maintenance" — recorded in the event log as an intentional action.
SHTDN_REASON_FLAG_PLANNED = 0x80000000
SHTDN_REASON_MAJOR_APPLICATION = 0x00040000
SHTDN_REASON_MINOR_MAINTENANCE = 0x1
REASON = SHTDN_REASON_FLAG_PLANNED | SHTDN_REASON_MAJOR_APPLICATION | SHTDN_REASON_MINOR_MAINTENANCE

SE_PRIVILEGE_ENABLED = 0x2
TOKEN_ADJUST_PRIVILEGES = 0x20
TOKEN_QUERY = 0x8


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


def _enable_shutdown_privilege() -> None:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                     ctypes.byref(token)):
        raise PlatformError("Could not open the process token.")
    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeShutdownPrivilege", ctypes.byref(luid)):
            raise PlatformError("Shutdown privilege is not available.")
        privileges = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
        advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None)
        if ctypes.get_last_error() != 0:
            raise PlatformError("Windows did not grant permission to shut down.")
    finally:
        kernel32.CloseHandle(token)


def _exit_windows(flags: int, what: str) -> None:
    _require_windows()
    if flags != EWX_LOGOFF:
        _enable_shutdown_privilege()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if not user32.ExitWindowsEx(flags, REASON):
        raise PlatformError(f"Windows refused to {what} (error {ctypes.get_last_error()}).")


def shutdown(force_if_hung: bool = True) -> None:
    _exit_windows(EWX_SHUTDOWN | EWX_POWEROFF | (EWX_FORCEIFHUNG if force_if_hung else 0), "shut down")


def restart(force_if_hung: bool = True) -> None:
    _exit_windows(EWX_REBOOT | (EWX_FORCEIFHUNG if force_if_hung else 0), "restart")


def sign_out() -> None:
    _exit_windows(EWX_LOGOFF, "sign out")


def _powrprof():
    _require_windows()
    lib = ctypes.WinDLL("powrprof", use_last_error=True)
    lib.SetSuspendState.argtypes = [wintypes.BOOLEAN, wintypes.BOOLEAN, wintypes.BOOLEAN]
    lib.SetSuspendState.restype = wintypes.BOOLEAN
    lib.IsPwrHibernateAllowed.restype = wintypes.BOOLEAN
    lib.IsPwrSuspendAllowed.restype = wintypes.BOOLEAN
    return lib


def hibernate_available() -> bool:
    return bool(_powrprof().IsPwrHibernateAllowed())


def sleep() -> None:
    lib = _powrprof()
    if not lib.IsPwrSuspendAllowed():
        raise PlatformError("Sleep is not available on this PC.")
    # Note: with hibernation enabled, SetSuspendState(FALSE) still sleeps (documented behaviour
    # differs; Hybrid Sleep may apply depending on the power plan).
    if not lib.SetSuspendState(False, False, False):
        raise PlatformError(f"Windows refused to sleep (error {ctypes.get_last_error()}).")


def hibernate() -> None:
    lib = _powrprof()
    if not lib.IsPwrHibernateAllowed():
        raise PlatformError("Hibernate is turned off on this PC. Enable it with 'powercfg /hibernate on'.")
    if not lib.SetSuspendState(True, False, False):
        raise PlatformError(f"Windows refused to hibernate (error {ctypes.get_last_error()}).")
