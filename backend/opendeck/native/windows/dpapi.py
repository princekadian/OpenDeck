"""Windows DPAPI: encrypt small secrets (the OBS password) for the current Windows user.

Only this Windows account on this PC can decrypt them; copying the database
elsewhere does not reveal the password.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .session import PlatformError, _require_windows

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _call(fn_name: str, data: bytes) -> bytes:
    _require_windows()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32")
    source, out = _blob(data), DATA_BLOB()
    fn = getattr(crypt32, fn_name)
    if not fn(ctypes.byref(source), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise PlatformError(f"{fn_name} failed (error {ctypes.get_last_error()}).")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(data: bytes) -> bytes:
    return _call("CryptProtectData", data)


def unprotect(data: bytes) -> bytes:
    return _call("CryptUnprotectData", data)
