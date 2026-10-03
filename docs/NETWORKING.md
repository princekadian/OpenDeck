# Networking

OpenDeck is a local-network app. Phones and tablets connect directly to the PC over Wi-Fi;
nothing goes through the internet.

## Ports

| Listener | Address | Who uses it |
|---|---|---|
| Remote-control server | `0.0.0.0:8765` by default (Settings → Server) | phones/tablets (HTTP + WebSocket) |
| Engine control | `127.0.0.1:<random port>` | the desktop window only; not reachable from the network |
| Desktop host control | `127.0.0.1:<random port>`, token-protected | the desktop window's bridge only |

"Accept connections from: This PC only" binds the remote server to `127.0.0.1`, so no device can reach it.

## Which address is shown

The Dashboard shows `http://<address>:<port>` for the adapter Windows routes traffic through
(typically Wi-Fi or Ethernet). Host-only virtual adapters (Hyper-V `vEthernet`, VirtualBox, VMware,
WSL) have no gateway and are not reachable from phones, so they are hidden. If you have several real
networks, choose one in Settings → Remote control → Address shown to devices.

## Firewall

- The installer adds an inbound rule for `OpenDeck.exe` on **Private** networks only. Public
  networks (cafés, airports) stay blocked. Uninstalling removes the rule.
- Set your home Wi-Fi to **Private**: Windows Settings → Network & internet → Wi-Fi → your network →
  Network profile type → Private.
- Running from source (no installer)? Allow the port once from an elevated PowerShell:

  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\allow-firewall.ps1 -Port 8765
  ```

OpenDeck never changes firewall settings by itself at runtime.

## The server also refuses non-local clients

Even if a port were forwarded, the server rejects any client outside private address ranges
(10/8, 172.16/12, 192.168/16, link-local, IPv6 ULA). Do not port-forward it anyway: traffic is plain
HTTP.

## When a device can't connect

1. Dashboard: is the server **Running**? Does it show an error such as "Port 8765 is already in use"?
2. Same network? Guest networks and "AP/client isolation" on routers block device-to-device traffic.
3. Wi-Fi profile set to Private (see above)?
4. Firewall rule present? (`Get-NetFirewallRule -DisplayName "OpenDeck*"` in PowerShell.)
5. VPN on the PC can change the route; disconnect it or pick the right address in Settings.
6. Open the address on the PC itself: if it works there but not on the phone, it's network or firewall.

Logs (Logs page, or `%LOCALAPPDATA%\OpenDeck\logs\server.log`) show every device connection,
disconnection and refused client.
