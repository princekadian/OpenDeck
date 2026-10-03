"""Network state: the routed interface's traffic, Wi-Fi details, and Internet reachability.

- Interface: GetBestInterfaceEx picks the adapter Windows would route Internet traffic
  through (a routing-table lookup; nothing is sent), so virtual adapters (Hyper-V,
  VirtualBox, VPN taps that aren't the default route) are not counted.
- Traffic: GetIfEntry2 byte counters for that interface.
- Wi-Fi: wlanapi. Windows 11 may hide the network name and signal from apps without
  location permission; the connection state is still available.
- Internet: Windows' own connectivity check (NCSI) via INetworkListManager. We send nothing.
"""

from __future__ import annotations

import ctypes
import socket
from ctypes import wintypes
from dataclasses import dataclass

from . import com
from .session import _require_windows

IF_TYPE_IEEE80211 = 71
NDIS_PHYSICAL_MEDIUM_NATIVE_802_11 = 9
NDIS_PHYSICAL_MEDIUM_WIRELESS_WAN = 8
IF_OPER_STATUS_UP = 1

CLSID_NETWORK_LIST_MANAGER = "{DCB00C01-570F-4A9B-8D69-199FDBA5723B}"
IID_INETWORK_LIST_MANAGER = "{DCB00000-570F-4A9B-8D69-199FDBA5723B}"
NLM_CONNECTIVITY_IPV4_INTERNET = 0x40
NLM_CONNECTIVITY_IPV6_INTERNET = 0x400

WLAN_INTF_OPCODE_CURRENT_CONNECTION = 7
WLAN_INTERFACE_STATE_CONNECTED = 1

_iphlp = None
_wlan = None


class MIB_IF_ROW2(ctypes.Structure):
    _fields_ = [
        ("InterfaceLuid", ctypes.c_uint64), ("InterfaceIndex", wintypes.ULONG), ("InterfaceGuid", com.GUID),
        ("Alias", ctypes.c_wchar * 257), ("Description", ctypes.c_wchar * 257),
        ("PhysicalAddressLength", wintypes.ULONG), ("PhysicalAddress", ctypes.c_ubyte * 32),
        ("PermanentPhysicalAddress", ctypes.c_ubyte * 32), ("Mtu", wintypes.ULONG), ("Type", wintypes.ULONG),
        ("TunnelType", ctypes.c_int), ("MediaType", ctypes.c_int), ("PhysicalMediumType", ctypes.c_int),
        ("AccessType", ctypes.c_int), ("DirectionType", ctypes.c_int), ("InterfaceAndOperStatusFlags", ctypes.c_ubyte),
        ("OperStatus", ctypes.c_int), ("AdminStatus", ctypes.c_int), ("MediaConnectState", ctypes.c_int),
        ("NetworkGuid", com.GUID), ("ConnectionType", ctypes.c_int),
        ("TransmitLinkSpeed", ctypes.c_uint64), ("ReceiveLinkSpeed", ctypes.c_uint64),
        ("InOctets", ctypes.c_uint64), ("InUcastPkts", ctypes.c_uint64), ("InNUcastPkts", ctypes.c_uint64),
        ("InDiscards", ctypes.c_uint64), ("InErrors", ctypes.c_uint64), ("InUnknownProtos", ctypes.c_uint64),
        ("InUcastOctets", ctypes.c_uint64), ("InMulticastOctets", ctypes.c_uint64),
        ("InBroadcastOctets", ctypes.c_uint64), ("OutOctets", ctypes.c_uint64), ("OutUcastPkts", ctypes.c_uint64),
        ("OutNUcastPkts", ctypes.c_uint64), ("OutDiscards", ctypes.c_uint64), ("OutErrors", ctypes.c_uint64),
        ("OutUcastOctets", ctypes.c_uint64), ("OutMulticastOctets", ctypes.c_uint64),
        ("OutBroadcastOctets", ctypes.c_uint64), ("OutQLen", ctypes.c_uint64),
    ]


assert ctypes.sizeof(MIB_IF_ROW2) == 1352, "MIB_IF_ROW2 layout mismatch"


class SOCKADDR_IN(ctypes.Structure):
    _fields_ = [("sin_family", ctypes.c_short), ("sin_port", ctypes.c_ushort),
                ("sin_addr", ctypes.c_ubyte * 4), ("sin_zero", ctypes.c_ubyte * 8)]


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", com.GUID), ("strInterfaceDescription", ctypes.c_wchar * 256), ("isState", ctypes.c_int)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD),
                ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * 32)]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("dot11Ssid", DOT11_SSID), ("dot11BssType", ctypes.c_int), ("dot11Bssid", ctypes.c_ubyte * 6),
                ("dot11PhyType", ctypes.c_int), ("uDot11PhyIndex", wintypes.ULONG),
                ("wlanSignalQuality", wintypes.ULONG), ("ulRxRate", wintypes.ULONG), ("ulTxRate", wintypes.ULONG)]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("isState", ctypes.c_int), ("wlanConnectionMode", ctypes.c_int),
                ("strProfileName", ctypes.c_wchar * 256), ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES)]


@dataclass(frozen=True)
class InterfaceInfo:
    index: int
    name: str  # "Wi-Fi", "Ethernet"
    description: str
    wireless: bool
    up: bool
    link_bps: int  # negotiated receive speed
    rx_bytes: int
    tx_bytes: int


@dataclass(frozen=True)
class WifiInfo:
    connected: bool
    ssid: str | None  # None when Windows withholds it (location permission)
    signal: int | None  # 0..100
    rx_kbps: int | None


def _iphlpapi():
    global _iphlp
    if _iphlp is None:
        _require_windows()
        _iphlp = ctypes.WinDLL("iphlpapi")
        _iphlp.GetBestInterfaceEx.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        _iphlp.GetBestInterfaceEx.restype = wintypes.DWORD
        _iphlp.GetIfEntry2.argtypes = [ctypes.POINTER(MIB_IF_ROW2)]
        _iphlp.GetIfEntry2.restype = wintypes.DWORD
    return _iphlp


def default_interface_index() -> int | None:
    """Index of the interface Windows routes Internet traffic through (no packets sent)."""
    target = SOCKADDR_IN(sin_family=socket.AF_INET)
    target.sin_addr[:] = (8, 8, 8, 8)
    index = wintypes.DWORD()
    if _iphlpapi().GetBestInterfaceEx(ctypes.byref(target), ctypes.byref(index)):
        return None
    return index.value


def interface(index: int) -> InterfaceInfo | None:
    row = MIB_IF_ROW2(InterfaceIndex=index)
    if _iphlpapi().GetIfEntry2(ctypes.byref(row)):
        return None
    wireless = row.Type == IF_TYPE_IEEE80211 or row.PhysicalMediumType in (
        NDIS_PHYSICAL_MEDIUM_NATIVE_802_11, NDIS_PHYSICAL_MEDIUM_WIRELESS_WAN)
    return InterfaceInfo(index, row.Alias, row.Description, wireless, row.OperStatus == IF_OPER_STATUS_UP,
                         row.ReceiveLinkSpeed, row.InOctets, row.OutOctets)


def _wlanapi():
    global _wlan
    if _wlan is None:
        _require_windows()
        _wlan = ctypes.WinDLL("wlanapi")
        _wlan.WlanOpenHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                         ctypes.POINTER(wintypes.HANDLE)]
        _wlan.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        _wlan.WlanQueryInterface.argtypes = [wintypes.HANDLE, ctypes.POINTER(com.GUID), ctypes.c_int, ctypes.c_void_p,
                                             ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p),
                                             ctypes.c_void_p]
        _wlan.WlanFreeMemory.argtypes = [ctypes.c_void_p]
        _wlan.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        for fn in ("WlanOpenHandle", "WlanEnumInterfaces", "WlanQueryInterface", "WlanCloseHandle"):
            getattr(_wlan, fn).restype = wintypes.DWORD
    return _wlan


class WlanClient:
    """Keeps one wlanapi handle; None from wifi() means this PC has no Wi-Fi adapter."""

    def __init__(self) -> None:
        self._handle = wintypes.HANDLE()
        negotiated = wintypes.DWORD()
        if _wlanapi().WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(self._handle)):
            self._handle = None  # WLAN service not running / no Wi-Fi hardware

    def wifi(self) -> WifiInfo | None:
        if not self._handle:
            return None
        api = _wlanapi()
        raw = ctypes.c_void_p()
        if api.WlanEnumInterfaces(self._handle, None, ctypes.byref(raw)) or not raw.value:
            return None
        try:
            count = ctypes.cast(raw, ctypes.POINTER(wintypes.DWORD))[0]
            if not count:
                return None
            items = ctypes.cast(raw.value + 8, ctypes.POINTER(WLAN_INTERFACE_INFO))
            infos = [items[i] for i in range(count)]
            info = next((i for i in infos if i.isState == WLAN_INTERFACE_STATE_CONNECTED), infos[0])
            connected = info.isState == WLAN_INTERFACE_STATE_CONNECTED
            guid = com.GUID.from_buffer_copy(info.InterfaceGuid)
        finally:
            api.WlanFreeMemory(raw)
        if not connected:
            return WifiInfo(False, None, None, None)
        size, data = wintypes.DWORD(), ctypes.c_void_p()
        if api.WlanQueryInterface(self._handle, ctypes.byref(guid), WLAN_INTF_OPCODE_CURRENT_CONNECTION, None,
                                  ctypes.byref(size), ctypes.byref(data), None) or not data.value:
            return WifiInfo(True, None, None, None)  # e.g. no location permission
        try:
            attrs = ctypes.cast(data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES))[0].wlanAssociationAttributes
            length = min(attrs.dot11Ssid.uSSIDLength, 32)
            ssid = bytes(attrs.dot11Ssid.ucSSID[:length]).decode("utf-8", "replace") or None
            return WifiInfo(True, ssid, int(attrs.wlanSignalQuality), int(attrs.ulRxRate) or None)
        finally:
            api.WlanFreeMemory(data)

    def close(self) -> None:
        if self._handle:
            _wlanapi().WlanCloseHandle(self._handle, None)
            self._handle = None


def internet_connected(manager: com.ComPtr) -> bool:
    """Windows' own verdict (NCSI): IPv4 or IPv6 Internet connectivity."""
    flags = ctypes.c_int()
    manager.hr(13, "INetworkListManager.GetConnectivity", [ctypes.POINTER(ctypes.c_int)], ctypes.byref(flags))
    return bool(flags.value & (NLM_CONNECTIVITY_IPV4_INTERNET | NLM_CONNECTIVITY_IPV6_INTERNET))


def network_list_manager() -> com.ComPtr:
    """Create on the thread that will use it (COM must be initialised there)."""
    return com.create(CLSID_NETWORK_LIST_MANAGER, IID_INETWORK_LIST_MANAGER)
