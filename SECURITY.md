# Security

## Model

OpenDeck runs actions on your PC, so the design limits who can trigger them and what they can do:

- **Only paired devices** can press buttons. Pairing needs a 6-digit code shown only on the PC
  (single use, 5-minute lifetime, locked after 5 wrong attempts). Devices then hold a random
  256-bit token; the PC stores only its SHA-256 hash. Removing a device disconnects it at once.
- **Devices send button IDs, never commands.** The engine looks up the button's stored action,
  validates it and runs it. Action settings (paths, URLs, scripts) are never sent to devices.
- **Only this PC can configure.** The editor and every `/api/admin` endpoint accept loopback
  clients only. The engine's control listener and the desktop host's endpoint bind `127.0.0.1`;
  the host endpoint also requires a random per-run token.
- **Local network only.** The server refuses clients outside private address ranges. The installer's
  firewall rule allows the app on Private networks only. No cloud service, account or telemetry.
- **Secrets.** The OBS password is encrypted with Windows DPAPI. Tokens, pairing codes and passwords
  are never logged.

## Known limits

- Traffic between devices and the PC is plain HTTP on your LAN. Anyone on the same network who
  can capture traffic could see button presses and could replay a captured device token. Use a
  network you trust; do not expose OpenDeck to the internet or port-forward it.
- Any program already running as you on the PC can use the loopback admin API (as it could change
  your files anyway).
- "Run command", "Run PowerShell" and HTTP actions run exactly what you configure, on the PC.

## Reporting a vulnerability

Please report privately (GitHub → Security → Report a vulnerability on the repository) rather than in
a public issue. Include steps to reproduce and the version (Settings → About). You'll get a reply as
soon as possible; fixes are released with a CHANGELOG note.
