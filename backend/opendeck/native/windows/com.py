"""Minimal COM plumbing over ctypes: GUIDs, vtable calls, PROPVARIANT, lifetime.

Only what the audio code needs. Interfaces are called by vtable index, which
is stable ABI for published Windows interfaces.
"""

from __future__ import annotations

import ctypes
import uuid
from ctypes import wintypes

CLSCTX_ALL = 0x17
COINIT_MULTITHREADED = 0x0
RPC_E_CHANGED_MODE = -2147417850


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "GUID":
        b = uuid.UUID(text).bytes_le
        return cls.from_buffer_copy(b)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    # Only the VT_LPWSTR case is read; the union is padded to its full size.
    _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD),
                ("r3", wintypes.WORD), ("pwszVal", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


ole32 = ctypes.WinDLL("ole32")
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.c_long
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
ole32.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]


class ComError(OSError):
    def __init__(self, what: str, hresult: int) -> None:
        super().__init__(f"{what} failed (HRESULT 0x{hresult & 0xFFFFFFFF:08X})")
        self.hresult = hresult


def init_thread() -> None:
    hr = ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    if hr < 0 and hr != RPC_E_CHANGED_MODE:
        raise ComError("CoInitializeEx", hr)


def check(hr: int, what: str) -> None:
    if hr < 0:
        raise ComError(what, hr)


def create(clsid: str, iid: str) -> "ComPtr":
    ptr = ctypes.c_void_p()
    check(ole32.CoCreateInstance(ctypes.byref(GUID.parse(clsid)), None, CLSCTX_ALL,
                                 ctypes.byref(GUID.parse(iid)), ctypes.byref(ptr)), "CoCreateInstance")
    return ComPtr(ptr)


class ComPtr:
    """Owned interface pointer. Released on close/garbage collection."""

    def __init__(self, ptr: ctypes.c_void_p) -> None:
        self.ptr = ptr

    def call(self, index: int, restype, argtypes: list, *args):
        vtable = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
        return fn(self.ptr, *args)

    def hr(self, index: int, what: str, argtypes: list, *args) -> None:
        check(self.call(index, ctypes.c_long, argtypes, *args), what)

    def out_ptr(self, index: int, what: str, argtypes: list, *args) -> "ComPtr":
        out = ctypes.c_void_p()
        self.hr(index, what, [*argtypes, ctypes.POINTER(ctypes.c_void_p)], *args, ctypes.byref(out))
        return ComPtr(out)

    def release(self) -> None:
        if self.ptr:
            self.call(2, wintypes.ULONG, [])
            self.ptr = ctypes.c_void_p()

    def __enter__(self) -> "ComPtr":
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass
