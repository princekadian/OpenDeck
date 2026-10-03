# OpenDeck

Turn a phone or tablet into a Stream Deck–style control surface for your Windows PC.

OpenDeck is a Windows desktop app. You build pages of buttons in it, and any iPad, iPhone or
Android device on your Wi-Fi opens them in Safari or Chrome. Each key you tap runs an action on
the PC: launch apps, control audio and media, send hotkeys, switch OBS scenes, run multi-step
workflows. Everything stays on your PC and your local network; there is no account and no cloud.

- **Windows app**: editor, server control, devices, logs, settings. Lives in the notification area.
- **Phone or tablet**: the remote control. Nothing to install; open the address the app shows.

> OpenDeck was called MyStreamDeck during early development. The name lives in
> `backend/opendeck/branding.py` and `frontend/src/branding.ts`.

## Install

1. Download `OpenDeck-Setup-<version>.exe` from [Releases](https://github.com/princekadian/OpenDeck/releases) (or [build it](BUILD.md)).
2. Run it. It installs to `Program Files\OpenDeck`, adds a Start menu shortcut, and allows
   OpenDeck through Windows Firewall on **private** networks only.
3. Start **OpenDeck**. The window opens on the Dashboard and the server starts.

Requirements: Windows 10 or 11 (64-bit) with the Microsoft Edge WebView2 Runtime (built into
Windows 11 and current Windows 10). No Python, Node.js or terminal needed.

## Connect a phone or tablet

1. Dashboard → **Connect a phone or tablet** shows the address (for example `http://192.168.1.20:8765`),
   a QR code, and a 6-digit pairing code.
2. Scan the QR code (or type the address) on the device, then enter the pairing code.
3. Tap keys. Edits you make on the PC appear on the device immediately.

Tip: in Safari use *Share → Add to Home Screen* for a full-screen dashboard.
If a device can't connect, see [docs/NETWORKING.md](docs/NETWORKING.md).

## Using the app

| Section | What it does |
|---|---|
| Dashboard | Server state with Start / Stop / Restart, the remote address with Copy / Open / QR code, connected devices, version, CPU and memory |
| Editor | Profiles, pages, buttons, folders (nested), drag and drop, icons, actions, Test on this PC |
| Devices | Pairing code; paired devices with type, IP, status, last connection; rename and remove |
| System Monitoring | Live CPU, GPU, RAM, temperatures, network, disks, battery, Wi-Fi, Internet; which tiles devices show |
| Integrations | OBS Studio connection |
| Settings | Start with Windows, keep running in the notification area, server address and port, auto-start, log detail, data folder and backups |
| Logs | Live server log with search, level and component filters, pause, auto-scroll, copy, save; desktop app log |
| Diagnostics | Versions, process IDs, addresses, database and folder paths; one-click copy for bug reports |

Closing the window keeps OpenDeck (and the server) running in the notification area, unless
you turn that off in Settings. Right-click the tray icon for Start / Stop / Restart Server, Open
Remote Dashboard, Open Logs, Settings and Exit. The icon shows the server state (running, stopped,
starting, error) by shape as well as colour.

Stopping the server disconnects devices; you can keep editing while it is stopped.

## Actions

| Category | Notes |
|---|---|
| Open | Launch application, Open website, Open file, Open folder |
| System | Lock, Shutdown, Restart, Sleep, Hibernate, Sign out (these ask for a second tap on the device by default), Task Manager, Settings (choose a page) |
| Audio | Volume up/down/set (with the Windows volume pop-up), Mute, microphone level and mute, switch default output/microphone. Keys show the live level or mute state |
| Media | Play/Pause, Previous, Next, Stop (sent as media keys, which Windows routes to the active player), Volume up/down |
| Keyboard | Hotkey (recorded), Type text (any language), Key press, Key combination |
| Display | Brightness (laptop panels, and monitors with DDC/CI enabled), projection mode like Win+P, HDR on/off |
| Window | Minimize, Maximize, Close, Restore, Switch application, Move, Resize (active window) |
| Applications | Launch, Close (optionally force), Restart, Focus, Running state on the key |
| Navigation | Folders, Go to page, Go to profile, Go back (only on the device that pressed), Open folder, Open URL |
| Workflow | Multi Action (ordered steps), Delay, Toggle (two actions, remembered), Counter and Timer (shared by name across keys) |
| Advanced | Run PowerShell, Run command, Send HTTP request, WebSocket message. Written only in the PC editor |
| Streaming | OBS: start/stop streaming, start/stop/pause recording, change scene, toggle source, toggle microphone, toggle camera. Keys show Live, REC, the live scene and mute state |

Keyboard and window actions act on whatever is active on the PC, like a physical keyboard.
Windows does not let a normal app send input to apps running as administrator.

### OBS Studio

1. In OBS: Tools → WebSocket Server Settings → Enable WebSocket server (port 4455).
2. Show Connect Info → copy the password.
3. In OpenDeck: Integrations → Connect to OBS, paste the password, Save and connect.

The password is stored encrypted with Windows DPAPI (only your Windows account can read it) and is
never sent to devices.

## Where things are

| What | Where |
|---|---|
| Program | `C:\Program Files\OpenDeck\` (replaced on upgrade) |
| Database, icons | `%LOCALAPPDATA%\OpenDeck\data\` |
| Logs | `%LOCALAPPDATA%\OpenDeck\logs\` — `server.log`, `desktop.log` (2 MB × 5, rotated) |
| Backups | `%LOCALAPPDATA%\OpenDeck\backups\` — before every schema upgrade, and Settings → Back up now |

Upgrading never touches your data. Uninstalling asks whether to delete it (default: keep).
Coming from MyStreamDeck (the earlier name)? OpenDeck copies its data from
`%LOCALAPPDATA%\MyStreamDeck` or `%APPDATA%\MyStreamDeck` on first start and leaves the old folder
untouched; the installer removes the old MyStreamDeck program. Paired devices keep working.

## Security

- **Pairing.** A device must enter a 6-digit code shown only on the PC. Codes expire after
  5 minutes, work once, and are invalidated after 5 wrong attempts.
- **Device tokens.** Pairing issues a random 256-bit token; the PC stores only its SHA-256 hash.
  Removing a device in Devices disconnects it at once.
- **No remote commands.** Devices send a button ID only. The action and its settings come from the
  PC's database and are validated before running. Devices never receive action settings.
- **Configuration is PC-only.** The editor and all `/api/admin` endpoints refuse anything but
  this PC (loopback). Only someone at the PC can change what buttons do.
- **LAN only.** Clients outside private address ranges are refused; the firewall rule covers
  private networks only. Do not port-forward OpenDeck.
- Traffic is plain HTTP on your LAN, so use a network you trust. See [SECURITY.md](SECURITY.md).

## Troubleshooting

| Symptom | Check |
|---|---|
| Device can't open the address | Wi-Fi set to Private; same network (not a guest network); router client isolation; firewall ([docs/NETWORKING.md](docs/NETWORKING.md)) |
| Dashboard shows "Port … is already in use" | Another program uses the port. Settings → Server → Port, then Save |
| "PC offline" on the device | Server stopped, PC asleep, or Wi-Fi dropped. Devices reconnect on their own |
| Device sent back to pairing | It was removed in Devices. Pair again with a new code |
| Window says "The engine stopped" | Restart engine; details are in Logs (or `%LOCALAPPDATA%\OpenDeck\logs`) |
| Window stays blank | Install the WebView2 Runtime (see Install) |
| An app opens behind other windows | Windows limits background apps from taking focus; the app still starts |

Diagnostics → **Copy diagnostics** collects what an issue report needs.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements-dev.txt
cd frontend; npm install; npm run build; cd ..

cd backend
..\.venv\Scripts\python -m opendeck.desktop   # the desktop app (window + tray), from source
..\.venv\Scripts\python -m opendeck           # or: the server alone, editor at http://localhost:8765/editor
```

Tests: `cd backend; ..\.venv\Scripts\python -m pytest -q` and `cd frontend; npm test`.
More in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Building the exe and installer: [BUILD.md](BUILD.md).

## Architecture

```text
OpenDeck.exe (desktop app: tray, single instance, supervisor)
 ├─ engine process   FastAPI + Uvicorn, SQLite, action engine, monitoring, OBS
 │    ├─ 127.0.0.1:<private port>   the desktop window's UI and admin API
 │    └─ 0.0.0.0:8765               remote-control server for devices (start/stop on demand)
 └─ window process   WebView2 window, only while it is open
Phone / tablet browser ── Wi-Fi ── remote-control server (WebSocket, button IDs only)
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). WebSocket protocol: [docs/PROTOCOL.md](docs/PROTOCOL.md).

```text
backend/opendeck/    Python: engine, actions, database, Windows integration, desktop app
backend/tests/           pytest suite (unit, WebSocket, engine process, supervisor)
frontend/src/            React + TypeScript: device dashboard, editor, desktop app UI
packaging/               PyInstaller spec and launcher
installer/               Inno Setup script
assets/icons/            app and tray icons (generated by scripts/make_icons.py)
scripts/                 build.ps1, make_icons.py, allow-firewall.ps1
docs/                    architecture, protocol, development, networking
```

## License

[MIT](LICENSE). Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
