# Changelog

## 1.1.0 — 2026-10-17

### Added
- Sound effects category: Play sound (MP3, WAV, OGG, Opus, FLAC, M4A, WMA) with volume, output
  device, an optional second device for voice chat, and press-again behaviour; Stop all sounds.
- The installer is built on GitHub Actions (Build installer); version tags publish a release.
- README: building the installer and contributing changes with Git.

## 1.0.0 — 2026-10-03

First release as a Windows desktop application, under the new name **OpenDeck** (previously
MyStreamDeck).

### Added
- Desktop app (`OpenDeck.exe`): native window with Dashboard, Editor, Devices, System Monitoring,
  Integrations, Settings, Logs and Diagnostics. No browser or terminal needed on the PC.
- Notification-area icon showing server state, with Start / Stop / Restart Server, Open Remote
  Dashboard, Open Logs, Settings and Exit. Closing the window keeps the app running (configurable).
- Remote-control server you can start, stop and restart; explicit states; port-conflict detection.
- Remote address with Copy, Open and a locally generated QR code; virtual network adapters hidden.
- Settings: start with Windows, keep running in the tray, server host and port, auto-start,
  preferred address, log detail, backups.
- Logs page: live server log (server-sent events), search, level and component filters, pause,
  auto-scroll, copy, save; desktop app log. Rotating log files.
- Devices page: rename, remove, device type, IP address, status, last connection.
- Diagnostics page with one-click copy for bug reports.
- Installer (Inno Setup): shortcuts, optional start with Windows, firewall rule for private
  networks, clean upgrades, uninstall that keeps your data unless you choose otherwise.
- Volume keys show the Windows volume pop-up.
- System Monitoring page and folders (nested button containers).

### Changed
- Renamed from MyStreamDeck to OpenDeck: program, installer, data folder, log names, environment
  variables (`OPENDECK_*`), Python package (`opendeck`). The installer replaces an existing
  MyStreamDeck install; paired devices keep working.
- User data moved to `%LOCALAPPDATA%\OpenDeck` (data, logs, backups, cache). Existing MyStreamDeck
  data is copied on first start; the old folder is left untouched.
- Log file renamed to `server.log`; database backups go to `backups\`.

## 0.x

Development milestones: engine, WebSocket protocol, pairing, editor, profiles, pages, 71 actions,
OBS integration.
