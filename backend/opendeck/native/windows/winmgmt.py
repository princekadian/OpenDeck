"""Windows and processes: active-window control, finding an app's windows, closing apps."""

from __future__ import annotations

import ctypes
import ntpath
from ctypes import wintypes
from dataclasses import dataclass

from .session import PlatformError, _require_windows

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE, SW_SHOW = 3, 6, 9, 5
WM_CLOSE = 0x0010
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x1
SYNCHRONIZE = 0x100000
TH32CS_SNAPPROCESS = 0x2
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x2

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG),
                ("bottom", wintypes.LONG)]


@dataclass(frozen=True)
class AppWindow:
    hwnd: int
    title: str
    pid: int
    path: str


class _Api:
    def __init__(self) -> None:
        _require_windows()
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi")
        u, k = self.user32, self.kernel32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsZoomed.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindow.restype = wintypes.HWND
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.BringWindowToTop.argtypes = [wintypes.HWND]
        u.GetShellWindow.restype = wintypes.HWND
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
                                                      wintypes.DWORD]


_api_instance: _Api | None = None


def _api() -> _Api:
    global _api_instance
    if _api_instance is None:
        _api_instance = _Api()
    return _api_instance


# ---- processes -----------------------------------------------------------------


def process_path(pid: int) -> str:
    k = _api().kernel32
    handle = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        return buffer.value if k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else ""
    finally:
        k.CloseHandle(handle)


def process_ids_by_name() -> dict[str, list[int]]:
    """Lower-case exe file name -> pids. One cheap snapshot, no per-process handles."""
    k = _api().kernel32
    snapshot = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (None, wintypes.HANDLE(-1).value):
        raise PlatformError("Could not list running programs.")
    result: dict[str, list[int]] = {}
    try:
        entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            result.setdefault(entry.szExeFile.lower(), []).append(entry.th32ProcessID)
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    return result


def find_processes(app_path: str) -> list[int]:
    """Pids running `app_path`.

    Prefers processes at exactly that path. If none match, falls back to the file
    name: some programs are launchers that start the real app elsewhere (Windows 11
    System32\\notepad.exe starts the Store Notepad, many apps update into versioned
    folders).
    """
    name = ntpath.basename(app_path).lower()
    wanted = ntpath.normcase(ntpath.normpath(app_path))
    candidates = process_ids_by_name().get(name, [])
    exact = [pid for pid in candidates if ntpath.normcase(process_path(pid)) == wanted]
    return exact or candidates


def terminate(pid: int) -> bool:
    k = _api().kernel32
    handle = k.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return bool(k.TerminateProcess(handle, 1))
    finally:
        k.CloseHandle(handle)


# ---- windows -------------------------------------------------------------------


def _title(hwnd: int) -> str:
    u = _api().user32
    length = u.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    u.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _api().user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _is_app_window(hwnd: int) -> bool:
    """A window that would appear in Alt+Tab: visible, titled, unowned, not a tool window or cloaked."""
    api = _api()
    u = api.user32
    if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, GW_OWNER) or not u.GetWindowTextLengthW(hwnd):
        return False
    if u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
        return False
    cloaked = wintypes.DWORD()
    api.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return not cloaked.value


def app_windows() -> list[AppWindow]:
    """Top-level application windows in Z order (front first)."""
    found: list[AppWindow] = []
    paths: dict[int, str] = {}

    def visit(hwnd, _lparam):
        if _is_app_window(hwnd):
            pid = _pid(hwnd)
            if pid not in paths:
                paths[pid] = process_path(pid)
            found.append(AppWindow(int(hwnd), _title(hwnd), pid, paths[pid]))
        return True

    _api().user32.EnumWindows(WNDENUMPROC(visit), 0)
    return found


def windows_of(app_path: str) -> list[AppWindow]:
    pids = set(find_processes(app_path))
    return [w for w in app_windows() if w.pid in pids]


def foreground_window() -> int:
    u = _api().user32
    hwnd = u.GetForegroundWindow()
    if not hwnd or hwnd == u.GetShellWindow():
        raise PlatformError("No application window is active on the PC.")
    return int(hwnd)


def show(hwnd: int, command: int) -> None:
    _api().user32.ShowWindow(hwnd, command)


def is_minimized(hwnd: int) -> bool:
    return bool(_api().user32.IsIconic(hwnd))


def is_maximized(hwnd: int) -> bool:
    return bool(_api().user32.IsZoomed(hwnd))


def close_window(hwnd: int) -> None:
    """Ask the window to close, like clicking its X. The app may prompt to save."""
    if not _api().user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
        raise PlatformError("The window could not be closed.")


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = RECT()
    _api().user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def move_window(hwnd: int, x: int, y: int) -> None:
    if is_maximized(hwnd) or is_minimized(hwnd):
        show(hwnd, SW_RESTORE)
    _set_pos(hwnd, x, y, 0, 0, SWP_NOSIZE)


def resize_window(hwnd: int, width: int, height: int) -> None:
    if is_maximized(hwnd) or is_minimized(hwnd):
        show(hwnd, SW_RESTORE)
    _set_pos(hwnd, 0, 0, width, height, SWP_NOMOVE)


def _set_pos(hwnd: int, x: int, y: int, w: int, h: int, flags: int) -> None:
    if not _api().user32.SetWindowPos(hwnd, None, x, y, w, h, flags | SWP_NOZORDER | SWP_NOACTIVATE):
        raise PlatformError("Windows refused to move or resize the window.")


def focus_window(hwnd: int) -> None:
    """Bring a window to the front, restoring it if minimised.

    Windows only lets the process that received the last input change the
    foreground window; a synthetic Alt tap satisfies that rule (a documented
    technique) without side effects in the target app.
    """
    u = _api().user32
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, SW_RESTORE)
    u.keybd_event(VK_MENU, 0, 0, 0)
    u.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    u.SetForegroundWindow(hwnd)
    u.BringWindowToTop(hwnd)
