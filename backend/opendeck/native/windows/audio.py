"""Windows Core Audio: endpoint volume, mute and default device selection.

Uses the documented MMDevice + IAudioEndpointVolume interfaces. Changing the
default device uses IPolicyConfig, which Windows does not document but which the
Sound control panel itself uses (as do EarTrumpet and SoundSwitch).

All functions must run on a thread that called com.init_thread(); the
AudioService runs them on its own dedicated worker thread.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Literal

from . import com

Flow = Literal["output", "input"]
_FLOW = {"output": 0, "input": 1}  # eRender, eCapture
DEVICE_STATE_ACTIVE = 0x1
ROLES = (0, 1, 2)  # eConsole, eMultimedia, eCommunications

CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_IAudioEndpointVolume = "5CDF2C82-841E-4546-9722-0CF74078229A"
CLSID_PolicyConfigClient = "870AF99C-171D-4F9E-AF0D-E63DF40C2BC9"
IID_IPolicyConfig = "F8679F50-850A-41CF-9C72-430F290290C8"
PKEY_Device_FriendlyName = ("A45C254E-DF1C-4EFD-8020-67D146A850E0", 14)


class AudioError(OSError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    flow: Flow
    is_default: bool


def _enumerator() -> com.ComPtr:
    return com.create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)


def _device_id(device: com.ComPtr) -> str:
    out = ctypes.c_wchar_p()
    device.hr(5, "IMMDevice.GetId", [ctypes.POINTER(ctypes.c_wchar_p)], ctypes.byref(out))
    try:
        return out.value or ""
    finally:
        com.ole32.CoTaskMemFree(ctypes.cast(out, ctypes.c_void_p))


def _friendly_name(device: com.ComPtr) -> str:
    with device.out_ptr(4, "IMMDevice.OpenPropertyStore", [wintypes.DWORD], 0) as store:
        key = com.PROPERTYKEY(com.GUID.parse(PKEY_Device_FriendlyName[0]), PKEY_Device_FriendlyName[1])
        value = com.PROPVARIANT()
        store.hr(5, "IPropertyStore.GetValue", [ctypes.POINTER(com.PROPERTYKEY), ctypes.POINTER(com.PROPVARIANT)],
                 ctypes.byref(key), ctypes.byref(value))
        try:
            return value.pwszVal or "Audio device"
        finally:
            com.ole32.PropVariantClear(ctypes.byref(value))


def _default_device(enum: com.ComPtr, flow: Flow) -> com.ComPtr:
    try:
        return enum.out_ptr(4, "GetDefaultAudioEndpoint", [ctypes.c_int, ctypes.c_int], _FLOW[flow], 0)
    except com.ComError as exc:
        kind = "speaker or headphones" if flow == "output" else "microphone"
        raise AudioError("DEVICE_NOT_FOUND", f"No default {kind} is available.") from exc


def _device(enum: com.ComPtr, flow: Flow, device_id: str | None) -> com.ComPtr:
    if not device_id:
        return _default_device(enum, flow)
    try:
        return enum.out_ptr(5, "IMMDeviceEnumerator.GetDevice", [ctypes.c_wchar_p], device_id)
    except com.ComError as exc:
        raise AudioError("DEVICE_NOT_FOUND", "The selected audio device is not connected.") from exc


def _endpoint_volume(device: com.ComPtr) -> com.ComPtr:
    iid = com.GUID.parse(IID_IAudioEndpointVolume)
    return device.out_ptr(3, "IMMDevice.Activate",
                          [ctypes.POINTER(com.GUID), wintypes.DWORD, ctypes.c_void_p],
                          ctypes.byref(iid), com.CLSCTX_ALL, None)


def list_devices(flow: Flow) -> list[AudioDevice]:
    with _enumerator() as enum:
        try:
            with _default_device(enum, flow) as default:
                default_id = _device_id(default)
        except AudioError:
            default_id = ""
        devices: list[AudioDevice] = []
        with enum.out_ptr(3, "EnumAudioEndpoints", [ctypes.c_int, wintypes.DWORD],
                          _FLOW[flow], DEVICE_STATE_ACTIVE) as collection:
            count = wintypes.UINT()
            collection.hr(3, "GetCount", [ctypes.POINTER(wintypes.UINT)], ctypes.byref(count))
            for i in range(count.value):
                with collection.out_ptr(4, "Item", [wintypes.UINT], i) as device:
                    dev_id = _device_id(device)
                    devices.append(AudioDevice(dev_id, _friendly_name(device), flow, dev_id == default_id))
        return devices


def get_level(flow: Flow, device_id: str | None = None) -> tuple[float, bool]:
    """(volume 0..1, muted) for a device or the default device."""
    with _enumerator() as enum, _device(enum, flow, device_id) as device, _endpoint_volume(device) as vol:
        level = ctypes.c_float()
        vol.hr(9, "GetMasterVolumeLevelScalar", [ctypes.POINTER(ctypes.c_float)], ctypes.byref(level))
        muted = wintypes.BOOL()
        vol.hr(15, "GetMute", [ctypes.POINTER(wintypes.BOOL)], ctypes.byref(muted))
        return float(level.value), bool(muted.value)


def set_level(flow: Flow, level: float, device_id: str | None = None) -> float:
    level = min(1.0, max(0.0, level))
    with _enumerator() as enum, _device(enum, flow, device_id) as device, _endpoint_volume(device) as vol:
        vol.hr(7, "SetMasterVolumeLevelScalar", [ctypes.c_float, ctypes.c_void_p], level, None)
        if level > 0:
            # Changing the volume of a muted device should make it audible, like the tray slider.
            vol.hr(14, "SetMute", [wintypes.BOOL, ctypes.c_void_p], False, None)
    return level


def set_mute(flow: Flow, muted: bool, device_id: str | None = None) -> None:
    with _enumerator() as enum, _device(enum, flow, device_id) as device, _endpoint_volume(device) as vol:
        vol.hr(14, "SetMute", [wintypes.BOOL, ctypes.c_void_p], muted, None)


def set_default_device(device_id: str) -> None:
    """Make `device_id` the default for all roles (console, multimedia, communications)."""
    try:
        policy = com.create(CLSID_PolicyConfigClient, IID_IPolicyConfig)
    except com.ComError as exc:
        raise AudioError("UNSUPPORTED", "This version of Windows does not allow switching audio devices.") from exc
    with policy:
        for role in ROLES:
            policy.hr(13, "IPolicyConfig.SetDefaultEndpoint", [ctypes.c_wchar_p, ctypes.c_int], device_id, role)
