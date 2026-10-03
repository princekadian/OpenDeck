"""Notification-area (tray) icon with a right-click menu, via Shell_NotifyIcon (ctypes).

Runs its own thread with a hidden window and message loop. Other threads change the
icon/tooltip or show a notification by posting messages; menu clicks call back on the
tray thread, so callbacks must hand slow work to another thread.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0000
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_REFRESH = WM_APP + 2
WM_BALLOON = WM_APP + 3
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_ERROR = 0x1, 0x3
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", ctypes.c_wchar * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", ctypes.c_wchar * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, ctypes.c_void_p]
user32.CreateWindowExW.restype = wintypes.HWND
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, ctypes.c_void_p]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.DestroyIcon.argtypes = [wintypes.HICON]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


@dataclass
class MenuItem:
    label: str
    action: Callable[[], None] | None = None  # None = disabled text
    default: bool = False
    separator: bool = False


SEPARATOR = MenuItem("", separator=True)


class TrayIcon:
    def __init__(self, icons: dict[str, Path], menu: Callable[[], list[MenuItem]], on_open: Callable[[], None]) -> None:
        self._icon_paths = icons  # state -> .ico
        self._menu = menu  # built fresh each time it opens, so it shows current state
        self._on_open = on_open
        self._state = "stopped"
        self._tip = "OpenDeck"
        self._balloon: tuple[str, str, bool] | None = None
        self._hwnd = None
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._icons: dict[str, int] = {}
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._wndproc = WNDPROC(self._window_proc)  # keep a reference: ctypes callback

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(5)

    def set_state(self, state: str, tooltip: str) -> None:
        self._state, self._tip = state, tooltip[:127]
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_REFRESH, 0, 0)

    def notify(self, title: str, text: str, error: bool = False) -> None:
        self._balloon = (title[:63], text[:255], error)
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_BALLOON, 0, 0)

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self._thread.join(3)

    # ---- tray thread ------------------------------------------------------------------------

    def _run(self) -> None:
        instance = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW(lpfnWndProc=self._wndproc, hInstance=instance, lpszClassName="OpenDeckTray")
        user32.RegisterClassW(ctypes.byref(cls))
        self._hwnd = user32.CreateWindowExW(0, cls.lpszClassName, "OpenDeck", 0, 0, 0, 0, 0, None, None,
                                            instance, None)
        cx, cy = user32.GetSystemMetrics(SM_CXSMICON), user32.GetSystemMetrics(SM_CYSMICON)
        for state, path in self._icon_paths.items():
            handle = user32.LoadImageW(None, str(path), IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
            if handle:
                self._icons[state] = handle
        self._shell(NIM_ADD)
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for handle in self._icons.values():
            user32.DestroyIcon(handle)

    def _data(self, flags: int) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self._hwnd, uID=1, uFlags=flags,
                               uCallbackMessage=WM_TRAY)
        data.hIcon = self._icons.get(self._state) or self._icons.get("stopped") or 0
        data.szTip = self._tip
        return data

    def _shell(self, command: int) -> None:
        data = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        shell32.Shell_NotifyIconW(command, ctypes.byref(data))

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_TRAY:
                if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self._on_open()
                elif lparam == WM_RBUTTONUP:
                    self._show_menu()
                return 0
            if message == WM_REFRESH:
                self._shell(NIM_MODIFY)
                return 0
            if message == WM_BALLOON and self._balloon:
                title, text, error = self._balloon
                data = self._data(NIF_INFO)
                data.szInfoTitle, data.szInfo = title, text
                data.dwInfoFlags = NIIF_ERROR if error else NIIF_INFO
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
                return 0
            if message == self._taskbar_created:  # Explorer restarted: add the icon again
                self._shell(NIM_ADD)
                return 0
            if message == WM_CLOSE:
                self._shell(NIM_DELETE)
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("Tray message handling failed")
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self) -> None:
        items = self._menu()
        menu = user32.CreatePopupMenu()
        for index, item in enumerate(items, start=1):
            if item.separator:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                user32.AppendMenuW(menu, MF_STRING | (0 if item.action else MF_GRAYED), index, item.label)
                if item.default:
                    user32.SetMenuDefaultItem(menu, index, False)
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(self._hwnd)  # so the menu closes when clicking elsewhere
        chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, point.x, point.y, 0,
                                       self._hwnd, None)
        user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if chosen and items[chosen - 1].action:
            items[chosen - 1].action()  # type: ignore[misc]
