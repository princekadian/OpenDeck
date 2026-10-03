"""Displays: enumeration, brightness (DDC/CI, laptop panel via WMI), projection mode, HDR.

- External monitors: brightness over DDC/CI (dxva2). Many monitors support it; some
  have it disabled in their on-screen menu.
- Built-in laptop panels: brightness via WMI (WmiMonitorBrightnessMethods).
- Projection mode: SetDisplayConfig topology flags (same as Win+P).
- HDR: DisplayConfigSetDeviceInfo advanced-color state (same as the Settings switch).
"""

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes
from dataclasses import dataclass

from .session import PlatformError, _require_windows

MONITORINFOF_PRIMARY = 0x1
QDC_ONLY_ACTIVE_PATHS = 0x2
SDC_APPLY = 0x80
TOPOLOGY = {"internal": 0x1, "clone": 0x2, "extend": 0x4, "external": 0x8}
GET_SOURCE_NAME = 1
GET_ADVANCED_COLOR_INFO = 9
SET_ADVANCED_COLOR_STATE = 10
CREATE_NO_WINDOW = 0x08000000

MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [("hPhysicalMonitor", wintypes.HANDLE), ("szPhysicalMonitorDescription", wintypes.WCHAR * 128)]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class PATH_SOURCE(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class PATH_TARGET(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("rotation", ctypes.c_uint32),
                ("scaling", ctypes.c_uint32), ("refreshNum", ctypes.c_uint32), ("refreshDen", ctypes.c_uint32),
                ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", wintypes.BOOL),
                ("statusFlags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE), ("targetInfo", PATH_TARGET), ("flags", ctypes.c_uint32)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("raw", ctypes.c_byte * 64)]


class DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", LUID),
                ("id", ctypes.c_uint32)]


class SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("viewGdiDeviceName", wintypes.WCHAR * 32)]


class ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("value", ctypes.c_uint32),
                ("colorEncoding", ctypes.c_uint32), ("bitsPerColorChannel", ctypes.c_uint32)]


class SET_ADVANCED_COLOR(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("value", ctypes.c_uint32)]


assert ctypes.sizeof(PATH_INFO) == 72, "DISPLAYCONFIG_PATH_INFO layout"


@dataclass(frozen=True)
class Display:
    id: str  # GDI device name, e.g. \\.\DISPLAY1
    name: str
    primary: bool


def _user32():
    _require_windows()
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
    u.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DISPLAY_DEVICEW),
                                      wintypes.DWORD]
    return u


def _monitors() -> list[tuple[int, MONITORINFOEXW]]:
    u = _user32()
    found: list[tuple[int, MONITORINFOEXW]] = []

    def visit(hmon, _hdc, _rect, _lparam):
        info = MONITORINFOEXW(cbSize=ctypes.sizeof(MONITORINFOEXW))
        if u.GetMonitorInfoW(hmon, ctypes.byref(info)):
            found.append((hmon, info))
        return True

    u.EnumDisplayMonitors(None, None, MONITORENUMPROC(visit), 0)
    return found


def list_displays() -> list[Display]:
    u = _user32()
    displays = []
    for index, (_h, info) in enumerate(_monitors(), start=1):
        device = DISPLAY_DEVICEW(cb=ctypes.sizeof(DISPLAY_DEVICEW))
        name = f"Display {index}"
        if u.EnumDisplayDevicesW(info.szDevice, 0, ctypes.byref(device), 0) and device.DeviceString:
            name = f"{device.DeviceString} ({index})"
        displays.append(Display(info.szDevice, name, bool(info.dwFlags & MONITORINFOF_PRIMARY)))
    return displays


def _target(display_id: str) -> tuple[int, MONITORINFOEXW]:
    monitors = _monitors()
    for hmon, info in monitors:
        if (display_id and info.szDevice == display_id) or (not display_id and info.dwFlags & MONITORINFOF_PRIMARY):
            return hmon, info
    raise PlatformError("That display is not connected.")


# ---- brightness ------------------------------------------------------------------


def _physical(hmon: int):
    dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)
    count = wintypes.DWORD()
    if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count)) or not count.value:
        return dxva2, None
    monitors = (PHYSICAL_MONITOR * count.value)()
    if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count.value, monitors):
        return dxva2, None
    return dxva2, monitors


def _ddc_brightness(hmon: int, set_percent: int | None) -> int | None:
    dxva2, monitors = _physical(hmon)
    if monitors is None:
        return None
    try:
        handle = monitors[0].hPhysicalMonitor
        low, cur, high = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        if not dxva2.GetMonitorBrightness(handle, ctypes.byref(low), ctypes.byref(cur), ctypes.byref(high)):
            return None
        span = max(1, high.value - low.value)
        if set_percent is None:
            return round((cur.value - low.value) * 100 / span)
        raw = low.value + round(span * max(0, min(100, set_percent)) / 100)
        if not dxva2.SetMonitorBrightness(handle, raw):
            return None
        return max(0, min(100, set_percent))
    finally:
        dxva2.DestroyPhysicalMonitors(len(monitors), monitors)


def _wmi_brightness(set_percent: int | None) -> int | None:
    """Built-in panel via WMI. PowerShell is used because WMI COM from ctypes is impractical."""
    if set_percent is None:
        script = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop | Select-Object -First 1).CurrentBrightness"
    else:
        script = (f"Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
                  f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={int(set_percent)}}} | Out-Null; {int(set_percent)}")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=8, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = result.stdout.strip().splitlines()
    return int(out[-1]) if result.returncode == 0 and out and out[-1].strip().isdigit() else None


def get_brightness(display_id: str = "") -> int:
    hmon, _info = _target(display_id)
    value = _ddc_brightness(hmon, None)
    if value is None:
        value = _wmi_brightness(None)
    if value is None:
        raise PlatformError("This display does not allow brightness control from Windows.")
    return value


def set_brightness(percent: int, display_id: str = "") -> int:
    hmon, _info = _target(display_id)
    value = _ddc_brightness(hmon, percent)
    if value is None:
        value = _wmi_brightness(percent)
    if value is None:
        raise PlatformError("This display does not allow brightness control from Windows.")
    return value


# ---- projection mode -------------------------------------------------------------


def set_projection(mode: str) -> None:
    """mode: internal (PC screen only) | clone (Duplicate) | extend | external (Second screen only)."""
    _require_windows()
    user32 = ctypes.WinDLL("user32")
    result = user32.SetDisplayConfig(0, None, 0, None, SDC_APPLY | TOPOLOGY[mode])
    if result != 0:
        raise PlatformError("Windows could not switch displays. Is a second display connected?")


# ---- HDR -------------------------------------------------------------------------


def _active_paths() -> list[PATH_INFO]:
    user32 = ctypes.WinDLL("user32")
    n_paths, n_modes = ctypes.c_uint32(), ctypes.c_uint32()
    if user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), ctypes.byref(n_modes)):
        raise PlatformError("Could not read the display configuration.")
    paths = (PATH_INFO * n_paths.value)()
    modes = (MODE_INFO * n_modes.value)()
    if user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), paths, ctypes.byref(n_modes),
                                 modes, None):
        raise PlatformError("Could not read the display configuration.")
    return list(paths[: n_paths.value])


def _path_for(display_id: str) -> PATH_INFO:
    user32 = ctypes.WinDLL("user32")
    wanted = display_id or _target("")[1].szDevice
    for path in _active_paths():
        name = SOURCE_DEVICE_NAME()
        name.header = DEVICE_INFO_HEADER(GET_SOURCE_NAME, ctypes.sizeof(SOURCE_DEVICE_NAME),
                                         path.sourceInfo.adapterId, path.sourceInfo.id)
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(name)) == 0 and name.viewGdiDeviceName == wanted:
            return path
    raise PlatformError("That display is not connected.")


def hdr_state(display_id: str = "") -> tuple[bool, bool]:
    """(supported, enabled)"""
    _require_windows()
    path = _path_for(display_id)
    info = ADVANCED_COLOR_INFO()
    info.header = DEVICE_INFO_HEADER(GET_ADVANCED_COLOR_INFO, ctypes.sizeof(ADVANCED_COLOR_INFO),
                                     path.targetInfo.adapterId, path.targetInfo.id)
    if ctypes.WinDLL("user32").DisplayConfigGetDeviceInfo(ctypes.byref(info)) != 0:
        raise PlatformError("Could not read HDR status.")
    return bool(info.value & 0x1), bool(info.value & 0x2)


def set_hdr(enabled: bool, display_id: str = "") -> None:
    supported, _ = hdr_state(display_id)
    if not supported:
        raise PlatformError("This display does not support HDR.")
    path = _path_for(display_id)
    request = SET_ADVANCED_COLOR()
    request.header = DEVICE_INFO_HEADER(SET_ADVANCED_COLOR_STATE, ctypes.sizeof(SET_ADVANCED_COLOR),
                                        path.targetInfo.adapterId, path.targetInfo.id)
    request.value = 1 if enabled else 0
    if ctypes.WinDLL("user32").DisplayConfigSetDeviceInfo(ctypes.byref(request)) != 0:
        raise PlatformError("Windows could not change HDR on this display.")
