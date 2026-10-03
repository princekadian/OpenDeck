"""CPU time, memory and battery from kernel32 (cheap calls, no counters or WMI)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from .session import _require_windows

_k32 = None


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    @property
    def value(self) -> int:
        return (self.dwHighDateTime << 32) | self.dwLowDateTime


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class ProcessUsage:
    pid: int
    working_set: int  # bytes of RAM in use
    cpu_seconds: float  # total CPU time used so far


@dataclass(frozen=True)
class CpuTimes:
    idle: int
    total: int  # kernel (which includes idle) + user, in 100 ns units


@dataclass(frozen=True)
class Memory:
    total: int  # bytes
    available: int


@dataclass(frozen=True)
class Battery:
    percent: int | None
    plugged_in: bool | None
    charging: bool


def _api():
    global _k32
    if _k32 is None:
        _require_windows()
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _k32.GetSystemTimes.argtypes = [ctypes.POINTER(FILETIME)] * 3
        _k32.GetSystemTimes.restype = wintypes.BOOL
        _k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
        _k32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        _k32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
        _k32.GetSystemPowerStatus.restype = wintypes.BOOL
        _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        _k32.OpenProcess.restype = wintypes.HANDLE
        _k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                                 wintypes.DWORD]
        _k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FILETIME)] * 4
        _k32.GetProcessTimes.restype = wintypes.BOOL
        _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return _k32


def cpu_times() -> CpuTimes:
    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    if not _api().GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError(ctypes.get_last_error(), "GetSystemTimes failed")
    return CpuTimes(idle.value, kernel.value + user.value)


def cpu_usage(before: CpuTimes, after: CpuTimes) -> float | None:
    """Percent busy across all cores between two readings."""
    total = after.total - before.total
    if total <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * (1 - (after.idle - before.idle) / total)))


def memory() -> Memory:
    status = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    if not _api().GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError(ctypes.get_last_error(), "GlobalMemoryStatusEx failed")
    return Memory(status.ullTotalPhys, status.ullAvailPhys)


def battery() -> Battery | None:
    """None on PCs without a battery (desktops)."""
    status = SYSTEM_POWER_STATUS()
    if not _api().GetSystemPowerStatus(ctypes.byref(status)):
        return None
    flag = status.BatteryFlag
    if flag & 128 or flag == 255:  # 128 = no system battery, 255 = unknown status
        return None
    percent = None if status.BatteryLifePercent == 255 else int(status.BatteryLifePercent)
    plugged = {0: False, 1: True}.get(status.ACLineStatus)
    return Battery(percent, plugged, bool(flag & 8))


def process_usage(pid: int) -> ProcessUsage | None:
    """RAM and CPU time of one process of this user (None if it is gone)."""
    api = _api()
    handle = api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        counters = PROCESS_MEMORY_COUNTERS(cb=ctypes.sizeof(PROCESS_MEMORY_COUNTERS))
        if not api.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        created, exited, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        api.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel),
                            ctypes.byref(user))
        return ProcessUsage(pid, counters.WorkingSetSize, (kernel.value + user.value) / 1e7)
    finally:
        api.CloseHandle(handle)

