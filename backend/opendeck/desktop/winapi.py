"""Small Win32 helpers for the desktop app (ctypes only, like the rest of the project)."""

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

from ..branding import PRODUCT_SLUG

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF
ASFW_ANY = 0xFFFFFFFF
SW_RESTORE = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9
MB_OK, MB_ICONERROR, MB_ICONINFORMATION = 0x0, 0x10, 0x40

# Per-session names: one app per Windows user session. Also used by the installer (AppMutex)
# to ask the user to close the app before upgrading.
MUTEX_NAME = f"Local\\{PRODUCT_SLUG}.Desktop"
SHOW_EVENT_NAME = f"Local\\{PRODUCT_SLUG}.ShowWindow"
EXIT_EVENT_NAME = f"Local\\{PRODUCT_SLUG}.Exit"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]

EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000


class SingleInstance:
    """Holds the per-session mutex; `first` is False if another copy already runs."""

    def __init__(self) -> None:
        self._handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        self.first = ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


def signal_show(name: str = SHOW_EVENT_NAME) -> bool:
    """Ask the running copy to show its window (we were just launched again), or to exit."""
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not handle:
        return False
    try:
        user32.AllowSetForegroundWindow(ASFW_ANY)  # let it come to the front
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


class ShowEvent:
    """Auto-reset event other launches set; `wait()` blocks until then."""

    def __init__(self, name: str = SHOW_EVENT_NAME) -> None:
        self._handle = kernel32.CreateEventW(None, False, False, name)

    def wait(self, timeout_ms: int = INFINITE) -> bool:
        return kernel32.WaitForSingleObject(self._handle, timeout_ms) == WAIT_OBJECT_0

    def set(self) -> None:
        kernel32.SetEvent(self._handle)


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class KillOnCloseJob:
    """Child processes in this job end when the desktop app ends, even if it crashes,
    so an engine can never be left running without its app."""

    def __init__(self) -> None:
        self._handle = kernel32.CreateJobObjectW(None, None)
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(self._handle, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                         ctypes.sizeof(info))

    def add(self, process: subprocess.Popen) -> None:
        kernel32.AssignProcessToJobObject(self._handle, wintypes.HANDLE(int(process._handle)))  # type: ignore[attr-defined]


def message_box(text: str, title: str, error: bool = False) -> None:
    user32.MessageBoxW(None, text, title, MB_OK | (MB_ICONERROR if error else MB_ICONINFORMATION))


def bring_process_window_to_front(pid: int) -> bool:
    """Restore and focus the visible top-level window of process `pid`."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(each, 0)
    if not found:
        return False
    hwnd = found[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True
