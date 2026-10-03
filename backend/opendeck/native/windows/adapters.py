"""Network adapters with IPv4 addresses (GetAdaptersAddresses), to show useful LAN URLs.

Phones reach the PC through an adapter on the same network as them: one with a
default gateway (a Wi-Fi or Ethernet network with a router). Host-only virtual adapters
(Hyper-V "vEthernet", VirtualBox, VMware) have no gateway and only make the list
confusing, so they are dropped unless nothing else exists.
"""

from __future__ import annotations

import ctypes
import socket
from ctypes import wintypes
from dataclasses import dataclass

from .session import _require_windows

AF_INET = 2
GAA_FLAG_SKIP_ANYCAST = 0x2
GAA_FLAG_SKIP_MULTICAST = 0x4
GAA_FLAG_SKIP_DNS_SERVER = 0x8
GAA_FLAG_INCLUDE_GATEWAYS = 0x80
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 131
IF_OPER_STATUS_UP = 1
ERROR_BUFFER_OVERFLOW = 111
_VIRTUAL_WORDS = ("hyper-v", "virtualbox", "vmware", "virtual", "vethernet", "wsl", "loopback", "npcap")


class SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]


class IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
    pass


IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG), ("Flags", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)), ("Address", SOCKET_ADDRESS),
]


class IP_ADAPTER_GATEWAY_ADDRESS(ctypes.Structure):
    pass


IP_ADAPTER_GATEWAY_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG), ("Reserved", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_GATEWAY_ADDRESS)), ("Address", SOCKET_ADDRESS),
]


class IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", wintypes.ULONG), ("IfIndex", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)), ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)), ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p), ("FirstDnsServerAddress", ctypes.c_void_p),
    ("DnsSuffix", ctypes.c_wchar_p), ("Description", ctypes.c_wchar_p), ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8), ("PhysicalAddressLength", wintypes.DWORD), ("Flags", wintypes.DWORD),
    ("Mtu", wintypes.DWORD), ("IfType", wintypes.DWORD), ("OperStatus", ctypes.c_int), ("Ipv6IfIndex", wintypes.DWORD),
    ("ZoneIndices", wintypes.DWORD * 16), ("FirstPrefix", ctypes.c_void_p),
    ("TransmitLinkSpeed", ctypes.c_uint64), ("ReceiveLinkSpeed", ctypes.c_uint64),
    ("FirstWinsServerAddress", ctypes.c_void_p), ("FirstGatewayAddress", ctypes.POINTER(IP_ADAPTER_GATEWAY_ADDRESS)),
]


@dataclass(frozen=True)
class Adapter:
    name: str  # "Wi-Fi"
    description: str
    addresses: tuple[str, ...]
    has_gateway: bool
    virtual: bool


def _ipv4(address: SOCKET_ADDRESS) -> str | None:
    if not address.lpSockaddr:
        return None
    raw = ctypes.string_at(address.lpSockaddr, 8)
    if int.from_bytes(raw[0:2], "little") != AF_INET:
        return None
    return socket.inet_ntoa(raw[4:8])


def adapters() -> list[Adapter]:
    _require_windows()
    iphlp = ctypes.WinDLL("iphlpapi")
    fn = iphlp.GetAdaptersAddresses
    fn.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
    fn.restype = wintypes.ULONG
    flags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER | GAA_FLAG_INCLUDE_GATEWAYS
    size = wintypes.ULONG(16 * 1024)
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        status = fn(AF_INET, flags, None, buffer, ctypes.byref(size))
        if status != ERROR_BUFFER_OVERFLOW:
            break
    if status != 0:
        return []
    out: list[Adapter] = []
    node = ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    while node:
        a = node.contents
        if a.OperStatus == IF_OPER_STATUS_UP and a.IfType not in (IF_TYPE_SOFTWARE_LOOPBACK, IF_TYPE_TUNNEL):
            addrs = []
            uni = a.FirstUnicastAddress
            while uni:
                ip = _ipv4(uni.contents.Address)
                if ip and not ip.startswith("169.254."):
                    addrs.append(ip)
                uni = uni.contents.Next
            if addrs:
                text = f"{a.FriendlyName or ''} {a.Description or ''}".lower()
                out.append(Adapter(a.FriendlyName or "", a.Description or "", tuple(addrs),
                                   bool(a.FirstGatewayAddress), any(w in text for w in _VIRTUAL_WORDS)))
        node = a.Next
    return out
