"""Native Windows file and folder pickers, shown on the PC for the local editor.

A browser cannot reveal a picked file's full path, so the editor asks the
server to show the standard Windows dialog instead.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Literal

from .session import _require_windows

PickKind = Literal["exe", "file", "folder", "audio"]

OFN_FILEMUSTEXIST = 0x1000
OFN_PATHMUSTEXIST = 0x800
OFN_NOCHANGEDIR = 0x8
OFN_EXPLORER = 0x80000
OFN_DONTADDTORECENT = 0x2000000
BIF_RETURNONLYFSDIRS = 0x1
BIF_EDITBOX = 0x10
BIF_NEWDIALOGSTYLE = 0x40
COINIT_APARTMENTTHREADED = 0x2
MAX_PATH_CHARS = 32768


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE), ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD), ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD), ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD), ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD), ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


class BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", wintypes.LPWSTR), ("lpszTitle", wintypes.LPCWSTR),
        ("ulFlags", wintypes.UINT), ("lpfn", ctypes.c_void_p),
        ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int),
    ]


_FILTERS = {
    "exe": "Applications (*.exe)\0*.exe\0All files (*.*)\0*.*\0\0",
    "file": "All files (*.*)\0*.*\0\0",
    "audio": "Audio files\0*.mp3;*.wav;*.ogg;*.oga;*.opus;*.flac;*.m4a;*.aac;*.wma\0All files (*.*)\0*.*\0\0",
}
_TITLES = {"exe": "Choose an application", "file": "Choose a file", "folder": "Choose a folder",
           "audio": "Choose a sound"}


def pick_path(kind: PickKind, initial: str | None = None) -> str | None:
    """Show the dialog (blocking) and return the chosen path, or None if cancelled."""
    _require_windows()
    ctypes.WinDLL("ole32").CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    # Owning the dialog by the foreground window (the editor's browser) keeps it on top.
    owner = ctypes.WinDLL("user32").GetForegroundWindow()
    return _pick_folder(owner) if kind == "folder" else _pick_file(kind, owner, initial)


def _pick_file(kind: PickKind, owner: int, initial: str | None) -> str | None:
    buffer = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
    dialog = OPENFILENAMEW()
    dialog.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    dialog.hwndOwner = owner
    dialog.lpstrFilter = _FILTERS[kind]
    dialog.nFilterIndex = 1
    dialog.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    dialog.nMaxFile = MAX_PATH_CHARS
    dialog.lpstrInitialDir = initial
    dialog.lpstrTitle = _TITLES[kind]
    dialog.Flags = (OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER
                    | OFN_DONTADDTORECENT)
    comdlg32 = ctypes.WinDLL("comdlg32")
    comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]
    if comdlg32.GetOpenFileNameW(ctypes.byref(dialog)):
        return buffer.value
    return None


def _pick_folder(owner: int) -> str | None:
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    display = ctypes.create_unicode_buffer(260)
    info = BROWSEINFOW(hwndOwner=owner, pszDisplayName=ctypes.cast(display, wintypes.LPWSTR),
                       lpszTitle=_TITLES["folder"],
                       ulFlags=BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX)
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
    if not pidl:
        return None
    try:
        path = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
        return path.value if shell32.SHGetPathFromIDListW(pidl, path) else None
    finally:
        ole32.CoTaskMemFree(pidl)
