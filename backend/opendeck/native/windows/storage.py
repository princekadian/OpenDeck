"""Local drives: space per drive letter and, where the disk reports it, temperature.

Temperature uses IOCTL_STORAGE_QUERY_PROPERTY(StorageDeviceTemperatureProperty), the
source of "Settings > Storage > Disks". The device is opened with no access rights, which
needs no administrator rights. Disks or drivers that don't report it give None.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from .session import _require_windows

DRIVE_FIXED = 3
OPEN_EXISTING = 3
FILE_SHARE_READ_WRITE = 0x1 | 0x2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
STORAGE_DEVICE_TEMPERATURE_PROPERTY = 52
PROPERTY_STANDARD_QUERY = 0

_k32 = None


class STORAGE_PROPERTY_QUERY(ctypes.Structure):
    _fields_ = [("PropertyId", ctypes.c_int), ("QueryType", ctypes.c_int), ("AdditionalParameters", ctypes.c_ubyte * 1)]


class STORAGE_TEMPERATURE_INFO(ctypes.Structure):
    _fields_ = [("Index", wintypes.WORD), ("Temperature", ctypes.c_short), ("OverThreshold", ctypes.c_short),
                ("UnderThreshold", ctypes.c_short), ("OverThresholdChangable", ctypes.c_ubyte),
                ("UnderThresholdChangable", ctypes.c_ubyte), ("EventGenerated", ctypes.c_ubyte),
                ("Reserved0", ctypes.c_ubyte), ("Reserved1", wintypes.DWORD)]


class STORAGE_TEMPERATURE_DATA_DESCRIPTOR(ctypes.Structure):
    _fields_ = [("Version", wintypes.DWORD), ("Size", wintypes.DWORD), ("CriticalTemperature", ctypes.c_short),
                ("WarningTemperature", ctypes.c_short), ("InfoCount", wintypes.WORD), ("Reserved0", ctypes.c_ubyte * 2),
                ("Reserved1", wintypes.DWORD * 2), ("TemperatureInfo", STORAGE_TEMPERATURE_INFO * 4)]


class STORAGE_DEVICE_NUMBER(ctypes.Structure):
    _fields_ = [("DeviceType", wintypes.DWORD), ("DeviceNumber", wintypes.DWORD), ("PartitionNumber", wintypes.DWORD)]


@dataclass(frozen=True)
class DriveSpace:
    drive: str  # "C:"
    total: int  # bytes
    free: int


def _api():
    global _k32
    if _k32 is None:
        _require_windows()
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _k32.GetLogicalDrives.restype = wintypes.DWORD
        _k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        _k32.GetDriveTypeW.restype = wintypes.UINT
        _k32.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
                                             ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong)]
        _k32.GetDiskFreeSpaceExW.restype = wintypes.BOOL
        _k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        _k32.CreateFileW.restype = wintypes.HANDLE
        _k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        _k32.DeviceIoControl.restype = wintypes.BOOL
        _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return _k32


def fixed_drives() -> list[DriveSpace]:
    """Local fixed drives (no USB sticks, network shares or optical drives)."""
    api = _api()
    mask = api.GetLogicalDrives()
    out: list[DriveSpace] = []
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        if api.GetDriveTypeW(root) != DRIVE_FIXED:
            continue
        free, total, _ = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if api.GetDiskFreeSpaceExW(root, ctypes.byref(free), ctypes.byref(total), ctypes.byref(_)) and total.value:
            out.append(DriveSpace(root[:2], total.value, free.value))
    return out


def _open(path: str):
    handle = _api().CreateFileW(path, 0, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None)
    return None if handle in (None, INVALID_HANDLE_VALUE) else handle


def disk_number(drive: str) -> int | None:
    """Physical disk number holding a drive letter ("C:" -> 1)."""
    handle = _open(f"\\\\.\\{drive}")
    if handle is None:
        return None
    try:
        number = STORAGE_DEVICE_NUMBER()
        returned = wintypes.DWORD()
        ok = _api().DeviceIoControl(handle, IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0, ctypes.byref(number),
                                    ctypes.sizeof(number), ctypes.byref(returned), None)
        return number.DeviceNumber if ok else None
    finally:
        _api().CloseHandle(handle)


def disk_temperature(number: int) -> float | None:
    """°C reported by physical disk `number`, or None when the disk doesn't report one."""
    handle = _open(f"\\\\.\\PhysicalDrive{number}")
    if handle is None:
        return None
    try:
        query = STORAGE_PROPERTY_QUERY(STORAGE_DEVICE_TEMPERATURE_PROPERTY, PROPERTY_STANDARD_QUERY)
        data = STORAGE_TEMPERATURE_DATA_DESCRIPTOR()
        returned = wintypes.DWORD()
        ok = _api().DeviceIoControl(handle, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query), ctypes.sizeof(query),
                                    ctypes.byref(data), ctypes.sizeof(data), ctypes.byref(returned), None)
        if not ok or not data.InfoCount:
            return None
        # Index 0 is the composite (whole-drive) sensor.
        temp = data.TemperatureInfo[0].Temperature
        # Some bridges report 0 or absurd values instead of "not supported".
        return float(temp) if 0 < temp < 150 else None
    finally:
        _api().CloseHandle(handle)
