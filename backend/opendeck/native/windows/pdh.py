"""Windows Performance Data Helper (PDH): one query, many counters, sampled together.

Used for counters with no direct API, e.g. GPU engine utilisation (the same source
Task Manager uses). Counter paths are English names so they work on any UI language.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .session import PlatformError, _require_windows

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2
PDH_CSTATUS_VALID_DATA = 0x0
PDH_CSTATUS_NEW_DATA = 0x1

_pdh = None


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", PDH_FMT_COUNTERVALUE)]


def _api():
    global _pdh
    if _pdh is None:
        _require_windows()
        _pdh = ctypes.WinDLL("pdh")
        _pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wintypes.HANDLE)]
        _pdh.PdhAddEnglishCounterW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_size_t,
                                               ctypes.POINTER(wintypes.HANDLE)]
        _pdh.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
        _pdh.PdhGetFormattedCounterArrayW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        _pdh.PdhCloseQuery.argtypes = [wintypes.HANDLE]
        for fn in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData",
                   "PdhGetFormattedCounterArrayW", "PdhCloseQuery"):
            getattr(_pdh, fn).restype = wintypes.DWORD
    return _pdh


class PdhQuery:
    """Wildcard counters ("\\GPU Engine(*)\\Utilization Percentage"); instances may come and go."""

    def __init__(self) -> None:
        self._query = wintypes.HANDLE()
        status = _api().PdhOpenQueryW(None, 0, ctypes.byref(self._query))
        if status:
            raise PlatformError(f"PdhOpenQuery failed (0x{status:08X})")
        self._counters: dict[str, wintypes.HANDLE] = {}

    def add(self, path: str) -> None:
        handle = wintypes.HANDLE()
        status = _api().PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(handle))
        if status:
            raise PlatformError(f"Counter not available: {path} (0x{status:08X})")
        self._counters[path] = handle

    def collect(self) -> None:
        # Rate counters need two collections; the first one after adding returns no data.
        _api().PdhCollectQueryData(self._query)

    def values(self, path: str) -> dict[str, float]:
        """Instance name -> value for a wildcard counter, from the last two collections."""
        handle = self._counters[path]
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        fmt = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        status = _api().PdhGetFormattedCounterArrayW(handle, fmt, ctypes.byref(size), ctypes.byref(count), None)
        if status != PDH_MORE_DATA or not size.value:
            return {}
        buffer = ctypes.create_string_buffer(size.value)
        status = _api().PdhGetFormattedCounterArrayW(handle, fmt, ctypes.byref(size), ctypes.byref(count), buffer)
        if status:
            return {}
        items = ctypes.cast(buffer, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
        out: dict[str, float] = {}
        for i in range(count.value):
            item = items[i]
            if item.FmtValue.CStatus in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA):
                out[item.szName] = out.get(item.szName, 0.0) + item.FmtValue.doubleValue
        return out

    def close(self) -> None:
        if self._query:
            _api().PdhCloseQuery(self._query)
            self._query = wintypes.HANDLE()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
