"""GPUs through the WDDM kernel thunks (D3DKMT*), vendor-neutral.

- Adapters: D3DKMTEnumAdapters2, with names and types from D3DKMTQueryAdapterInfo.
- Temperature: KMTQAITYPE_ADAPTERPERFDATA (WDDM 2.4+ drivers; the source Task Manager
  uses). Drivers that don't report it give 0, which we treat as "unavailable".
- Utilisation: PDH "GPU Engine" counters, grouped by adapter LUID; like Task Manager,
  a GPU's usage is its busiest engine type (3D, Copy, Video Decode, …).
"""

from __future__ import annotations

import ctypes
import re
from collections import defaultdict
from ctypes import wintypes
from dataclasses import dataclass

from .pdh import PdhQuery
from .session import PlatformError, _require_windows

KMTQAITYPE_ADAPTERREGISTRYINFO = 54
KMTQAITYPE_ADAPTERTYPE = 57
KMTQAITYPE_ADAPTERPERFDATA = 62

# D3DKMT_ADAPTERTYPE bit field
_SOFTWARE_DEVICE = 1 << 2
_HYBRID_INTEGRATED = 1 << 5
_INDIRECT_DISPLAY = 1 << 6
_RENDER_SUPPORTED = 1 << 0

GPU_ENGINE_COUNTER = r"\GPU Engine(*)\Utilization Percentage"
_INSTANCE = re.compile(r"luid_0x([0-9a-fA-F]+)_0x([0-9a-fA-F]+)_phys_(\d+)_eng_\d+_engtype_(.*)$")

_gdi = None


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class D3DKMT_ADAPTERINFO(ctypes.Structure):
    _fields_ = [("hAdapter", wintypes.UINT), ("AdapterLuid", LUID), ("NumOfSources", wintypes.ULONG),
                ("bPrecisePresentRegionsPreferred", wintypes.BOOL)]


class D3DKMT_ENUMADAPTERS2(ctypes.Structure):
    _fields_ = [("NumAdapters", wintypes.ULONG), ("pAdapters", ctypes.POINTER(D3DKMT_ADAPTERINFO))]


class D3DKMT_QUERYADAPTERINFO(ctypes.Structure):
    _fields_ = [("hAdapter", wintypes.UINT), ("Type", ctypes.c_int), ("pPrivateDriverData", ctypes.c_void_p),
                ("PrivateDriverDataSize", wintypes.UINT)]


class D3DKMT_CLOSEADAPTER(ctypes.Structure):
    _fields_ = [("hAdapter", wintypes.UINT)]


class D3DKMT_ADAPTER_PERFDATA(ctypes.Structure):
    _fields_ = [("PhysicalAdapterIndex", ctypes.c_uint32), ("MemoryFrequency", ctypes.c_uint64),
                ("MaxMemoryFrequency", ctypes.c_uint64), ("MaxMemoryFrequencyOC", ctypes.c_uint64),
                ("MemoryBandwidth", ctypes.c_uint64), ("PCIEBandwidth", ctypes.c_uint64),
                ("FanRPM", wintypes.ULONG), ("Power", wintypes.ULONG), ("Temperature", wintypes.ULONG),
                ("PowerStateOverride", ctypes.c_ubyte)]


class D3DKMT_ADAPTERREGISTRYINFO(ctypes.Structure):
    _fields_ = [("AdapterString", ctypes.c_wchar * 260), ("BiosString", ctypes.c_wchar * 260),
                ("DacType", ctypes.c_wchar * 260), ("ChipType", ctypes.c_wchar * 260)]


@dataclass(frozen=True)
class GpuAdapter:
    luid: str  # "0x00000000_0x0000D1B5", as in PDH instance names
    name: str
    integrated: bool


def _api():
    global _gdi
    if _gdi is None:
        _require_windows()
        _gdi = ctypes.WinDLL("gdi32")
        for fn in ("D3DKMTEnumAdapters2", "D3DKMTQueryAdapterInfo", "D3DKMTCloseAdapter"):
            getattr(_gdi, fn).restype = ctypes.c_long  # NTSTATUS
            getattr(_gdi, fn).argtypes = [ctypes.c_void_p]
    return _gdi


def _luid_key(luid: LUID) -> str:
    return f"0x{luid.HighPart & 0xFFFFFFFF:08X}_0x{luid.LowPart:08X}"


def _query(handle: int, kind: int, data: ctypes.Structure) -> bool:
    q = D3DKMT_QUERYADAPTERINFO(handle, kind, ctypes.cast(ctypes.byref(data), ctypes.c_void_p), ctypes.sizeof(data))
    return _api().D3DKMTQueryAdapterInfo(ctypes.byref(q)) == 0


def _enum() -> list[D3DKMT_ADAPTERINFO]:
    request = D3DKMT_ENUMADAPTERS2()
    if _api().D3DKMTEnumAdapters2(ctypes.byref(request)) != 0:
        raise PlatformError("D3DKMTEnumAdapters2 failed")
    infos = (D3DKMT_ADAPTERINFO * request.NumAdapters)()
    request.pAdapters = infos
    if _api().D3DKMTEnumAdapters2(ctypes.byref(request)) != 0:
        raise PlatformError("D3DKMTEnumAdapters2 failed")
    return list(infos[: request.NumAdapters])


def _close(handle: int) -> None:
    _api().D3DKMTCloseAdapter(ctypes.byref(D3DKMT_CLOSEADAPTER(handle)))


def hardware_adapters() -> list[GpuAdapter]:
    """Physical GPUs: no software renderers (WARP) or indirect/virtual displays (Parsec, RDP)."""
    out: list[GpuAdapter] = []
    for info in _enum():
        try:
            kind = wintypes.UINT()
            if not _query(info.hAdapter, KMTQAITYPE_ADAPTERTYPE, kind):
                continue
            flags = kind.value
            if not flags & _RENDER_SUPPORTED or flags & (_SOFTWARE_DEVICE | _INDIRECT_DISPLAY):
                continue
            reg = D3DKMT_ADAPTERREGISTRYINFO()
            name = reg.AdapterString.strip() if _query(info.hAdapter, KMTQAITYPE_ADAPTERREGISTRYINFO, reg) else ""
            key = _luid_key(info.AdapterLuid)
            if not any(a.luid == key for a in out):
                out.append(GpuAdapter(key, name or "GPU", bool(flags & _HYBRID_INTEGRATED)))
        finally:
            _close(info.hAdapter)
    # Discrete GPUs first: they are what "GPU" means to most people.
    return sorted(out, key=lambda a: a.integrated)


def temperatures() -> dict[str, float]:
    """LUID -> °C for adapters whose driver reports a temperature."""
    out: dict[str, float] = {}
    for info in _enum():
        try:
            perf = D3DKMT_ADAPTER_PERFDATA(PhysicalAdapterIndex=0)
            if _query(info.hAdapter, KMTQAITYPE_ADAPTERPERFDATA, perf) and perf.Temperature:
                out[_luid_key(info.AdapterLuid)] = perf.Temperature / 10  # deci-°C
        finally:
            _close(info.hAdapter)
    return out


class GpuUsageSampler:
    """Keeps one PDH query open; each sample() returns LUID -> percent since the previous one."""

    def __init__(self) -> None:
        self._query = PdhQuery()
        self._query.add(GPU_ENGINE_COUNTER)
        self._query.collect()

    def sample(self) -> dict[str, float]:
        self._query.collect()
        per_type: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for instance, value in self._query.values(GPU_ENGINE_COUNTER).items():
            match = _INSTANCE.search(instance)
            if match:
                luid = f"0x{match.group(1).upper()}_0x{match.group(2).upper()}"
                per_type[luid][match.group(4)] += value
        return {luid: min(100.0, max(types.values(), default=0.0)) for luid, types in per_type.items()}

    def close(self) -> None:
        self._query.close()
