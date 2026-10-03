"""Network helpers: client address classification and LAN address discovery."""

from __future__ import annotations

import ipaddress
import socket


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "testclient"  # Starlette TestClient


def is_lan(host: str | None) -> bool:
    """True for loopback, RFC1918, link-local and IPv6 ULA addresses."""
    if is_loopback(host):
        return True
    try:
        addr = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_private or addr.is_link_local


def lan_interfaces() -> list[dict[str, object]]:
    """IPv4 addresses phones can reach, with adapter names, the routed one first.

    Adapters without a gateway that look virtual (Hyper-V, VirtualBox, VMware) are
    marked so the UI can hide them; they are still listed for the Settings picker.
    """
    try:
        from ..native.windows.adapters import adapters

        found = adapters()
    except Exception:
        found = []
    primary = _routed_address()
    out: list[dict[str, object]] = []
    for adapter in found:
        for ip in adapter.addresses:
            if is_lan(ip):
                out.append({"address": ip, "name": adapter.name, "description": adapter.description,
                            "useful": adapter.has_gateway or not adapter.virtual})
    out.sort(key=lambda i: (i["address"] != primary, not i["useful"]))
    return out


def _routed_address() -> str | None:
    try:
        # UDP connect sends no packets; it only asks the OS which interface routes outward.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
    except OSError:
        return None


def lan_addresses() -> list[str]:
    """LAN IPv4 addresses worth showing to phones, primary first (virtual adapters left out)."""
    useful = [str(i["address"]) for i in lan_interfaces() if i["useful"]]
    if useful:
        return useful
    return _fallback_addresses()


def _fallback_addresses() -> list[str]:
    """Best-effort list of this PC's LAN IPv4 addresses, primary first."""
    found: list[str] = []
    try:
        # UDP connect sends no packets; it only asks the OS which interface routes outward.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(str(info[4][0]))
    except OSError:
        pass
    unique = [ip for i, ip in enumerate(found) if ip not in found[:i]]
    return [ip for ip in unique if is_lan(ip) and not ipaddress.ip_address(ip).is_loopback]
