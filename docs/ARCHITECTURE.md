# OpenDeck — Architecture

`OpenDeck` is a temporary internal name. Branding lives in `backend/opendeck/branding.py` only.

## 1. Overview

```text
 Phone / tablet (browser)                       Windows PC
┌──────────────────────┐                 ┌──────────────────────────────────────────────────────────┐
│ Control surface      │  Wi-Fi          │ OpenDeck.exe — desktop host (tray, single instance)  │
│ (React, /)           │                 │  ├─ supervises ──► engine process (OpenDeck.exe       │
│  - pages, folders    │  HTTP + WS /ws  │  │                  --engine): one FastAPI app, services   │
│  - device token      │◄───────────────►│  │    ├─ remote-control server 0.0.0.0:8765 (start/stop)  │
└──────────────────────┘  button IDs only│  │    ├─ control listener 127.0.0.1:<random> (window, API)│
                                         │  │    ├─ WS hub · action engine · state · monitoring · OBS │
                                         │  │    └─ SQLite (WAL, migrations) · logs                  │
                                         │  └─ opens ──► window process (OpenDeck.exe --ui):     │
                                         │                WebView2 showing /desktop (only while open)│
                                         └──────────────────────────────────────────────────────────┘
```

The engine is the authority. Devices send *intent* (`buttonId`), never commands; the engine
resolves the button from SQLite, validates the stored action and runs it. There is one engine,
one database and one action engine; the desktop window edits through the same admin API the
browser editor used, and devices get changes through the existing WebSocket snapshot push.

## 2. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Runtime | Python 3.12 | Existing engine; asyncio fits WebSocket + polling |
| HTTP/WS | FastAPI + Uvicorn + `websockets` | Mature, small, typed via Pydantic |
| DB | `sqlite3` stdlib | No ORM; hand-written, versioned SQL migrations |
| Windows APIs | `ctypes` (stdlib) | Win32/COM without pywin32 |
| Desktop window | pywebview → WebView2 | Reuses the existing React editor unchanged; WebView2 is part of Windows 10/11, so no bundled Chromium (unlike Electron). Python only: no second toolchain (Tauri would need Rust + MSVC for every contributor) |
| Tray, single instance, startup | ctypes: `Shell_NotifyIconW`, named mutex/events, HKCU Run value | Small, no extra dependencies |
| Frontend | React + TypeScript + Vite, plain CSS tokens | Small bundle; the desktop UI is a lazy chunk devices never load |
| Packaging | PyInstaller one-folder + Inno Setup | No Python/Node on the target; one-folder starts faster than one-file |

## 3. Directory structure

```text
backend/opendeck/
  __main__.py            python -m opendeck (headless) / --engine
  engine.py              engine process: lifespan, control listener, remote server, shutdown
  app.py                 composition root (services)
  config.py              data folders, import from MyStreamDeck
  logging_setup.py       rotating files + in-memory buffer (live log viewer)
  protocol.py            versioned WebSocket messages
  db/                    connection, migration runner, migrations/*.sql
  repositories/          SQL per aggregate
  actions/               Action contract, registry, engine, builtin/*
  native/windows/        Win32/COM wrappers (ctypes)
  services/              config, pairing, state, monitoring, audio, app settings, ...
  server/                http.py, ws.py (hub), admin_api.py, desktop_api.py, remote.py
  desktop/               host.py (tray, window, supervisor wiring), supervisor.py, tray.py, ui.py, winapi.py
backend/tests/
frontend/src/
  dashboard/             device control surface
  editor/                editor (standalone at /editor, embedded in the desktop app)
  desktop/               desktop app UI at /desktop: dashboard, settings, logs, devices, diagnostics
  monitor/               System Monitoring tiles (devices and desktop)
packaging/  installer/  assets/icons/  scripts/  docs/
```

## 3a. Desktop app

### Processes

| Process | Command | Lifetime | Job |
|---|---|---|---|
| Host | `OpenDeck.exe [--minimized]` | until Exit | single instance (mutex `Local\OpenDeck.Desktop`), tray, engine supervision, opens the window |
| Engine | `OpenDeck.exe --engine --control-port N` | while the host runs | everything in §4–§8a |
| Window | `OpenDeck.exe --ui ...` | while the window is open | WebView2 window on `http://127.0.0.1:N/desktop` |

Children are in a Windows job object with *kill on close*, so they can never outlive the host (even
if it crashes). Launching the exe again signals the running host (named event) to show its window;
`--exit` signals it to quit cleanly (used by the installer before upgrading).

### Engine lifecycle (desktop/supervisor.py)

`stopped → starting → running → stopping → stopped`, or `crashed`.

- Start: pick a free loopback port, spawn the engine, poll `GET /api/admin/health` until it answers
  (40 s limit). Only then "running".
- Crash: any exit not requested is logged with its exit code, shown in the tray (balloon + error
  icon) and in the window ("The engine stopped" with Restart engine).
- Stop: `POST /api/admin/shutdown` → the engine stops the remote server (closing device
  connections), the control listener, monitoring and OBS, closes the database, exits 0. After 12 s
  the host terminates it.
- Engine console output (failures before logging starts) goes to `logs/engine-console.log`.

### Remote-control server lifecycle (server/remote.py)

A second Uvicorn listener on the same app and services (no second backend). States `stopped,
starting, running, stopping, error`. Start checks the port with an exclusive bind first and
reports "Port N is already in use"; "running" is set only after Uvicorn has bound. Stop sets
`should_exit` (stop accepting, close WebSockets, finish in-flight requests, 5 s grace), then forces
if needed. `GET /api/admin/server/wait?since=v` is a long poll used by the tray and the window, so
neither polls for state. Settings changes to host/port restart it.

Headless mode (`python -m opendeck`) starts it at once and exits with it.

### Window ↔ host

The page talks to the engine over HTTP like the browser editor. For host-only things (engine
state, restart engine, exit, save file dialog) pywebview injects `window.pywebview.api`, which
calls a loopback HTTP endpoint on the host protected by a random per-run token.

### Settings and startup

Application settings are JSON in the existing `settings` table (key `app`): server host/port,
auto-start, minimize to tray, preferred address, log level. "Start with Windows" is the HKCU Run
value `OpenDeck = "<exe>" --minimized` (registered only by the installed exe); the registry is
the source of truth.

### Logging

`server.log` (engine) and `desktop.log` (host) in `%LOCALAPPDATA%\OpenDeck\logs`, 2 MB × 5 rotation,
format `time level component: message`. The engine also keeps the last 2000 records in memory with
sequence numbers; the Logs page streams new ones over server-sent events (`/api/admin/logs/stream`)
and reads files with a bounded tail (≤512 KB). Tokens, pairing codes and the OBS password are never
logged.

### Data and upgrades

```text
%LOCALAPPDATA%\OpenDeck\
  data\data.sqlite3, data\assets\     configuration (one database for everything)
  logs\                               server.log, desktop.log, engine/window console logs
  backups\                            data.vNNNN.bak before each migration; manual backups
  cache\webview\                      WebView2 profile of the window
```

On first start, OpenDeck copies the database of an earlier MyStreamDeck install
(`%LOCALAPPDATA%\MyStreamDeck\data\` from 1.0, else `%APPDATA%\MyStreamDeck\` from earlier) with SQLite's
online backup API, plus icons, and never modifies the original. The installer silently uninstalls
the old MyStreamDeck program (keeping its data) before installing OpenDeck. Migrations are versioned, run in a
transaction each, and are preceded by a backup. The installer only replaces program files.

### Installer (installer/OpenDeck.iss)

Inno Setup: Program Files (or per user), Start menu/desktop shortcuts, optional Run value, firewall
rule for the exe on private networks (admin installs), graceful `--exit` of a running copy before
upgrading, uninstall that keeps user data unless the user chooses otherwise.

## 4. Database schema (migrations 0001–0005)

```text
schema_migrations(version PK, applied_at)
settings(key PK, value)                       -- active_profile_id, seeded flag
profiles(id PK, name, description, icon_ref, sort_order, created_at, updated_at)
pages(id PK, profile_id FK→profiles CASCADE, name, icon_ref, sort_order, kind 'deck'|'monitor',
      created_at, updated_at)                  -- 0005: kind
buttons(id PK, page_id FK→pages CASCADE, parent_id FK→buttons CASCADE NULL,
        kind 'action'|'folder', sort_order, label, description, icon_ref,
        action_type, action_config JSON, appearance JSON, state_config JSON, enabled,
        created_at, updated_at)                -- 0004: parent_id, kind
devices(id PK, name, token_hash, paired_at, last_seen_at, revoked)
runtime_state(key PK, value JSON, updated_at)  -- 0003: toggle/counter/timer state
```

`pages.rows/cols` from 0001 remain but are unused: each device decides its own layout.
Migration 0002 rebuilt `buttons` from grid cells to `sort_order` (row-major), so Milestone 1
buttons keep their order. The database file is copied to `data.vNNNN.bak` before any migration.

### Folders (migration 0004)

A folder is a button with `kind = 'folder'`; it has no action and an empty `action_config`.
Buttons inside it point at it with `parent_id` (`NULL` = directly on the page). A container is
therefore `(page_id, parent_id)`, and `sort_order` is per container. Folders nest without a
depth limit. Every button in a folder tree has the same `page_id` as the folder, so moving a
folder to another page moves its subtree. Rules enforced in `ConfigService`:

- a button's `parent_id` must be a folder on the same page (`WRONG_PAGE`, 409);
- a folder can't be moved into itself or anything inside it (`CIRCULAR_FOLDER`, 409);
- a folder that still holds buttons can't become an action (`FOLDER_NOT_EMPTY`, 409);
- deleting a folder deletes its subtree (FK cascade); duplicating copies it with new ids;
- the action engine refuses to run a folder (`NOT_AN_ACTION`): folders never reach an executor.

Existing buttons became `kind = 'action'`, `parent_id = NULL`; nothing else changed.

`action_config` is a small JSON object owned and validated by the action's Pydantic model.
Icons are PNG files under `%APPDATA%\OpenDeck\assets\<sha256>.png`, referenced by `icon_ref`.
The editor converts uploads to a PNG of at most 256 × 256 px; exe icons are extracted to PNG.

### Editor API (loopback only, `/api/admin`)

| Area | Endpoints |
|---|---|
| Tree | `GET /config` (full configuration incl. action settings, plus the action catalog with JSON schemas) |
| Profiles | `POST /profiles`, `PATCH`/`DELETE /profiles/{id}`, `POST /profiles/{id}/duplicate`, `PUT /profiles-order`, `PUT /active-profile` |
| Pages | `POST /profiles/{id}/pages`, `PATCH`/`DELETE /pages/{id}`, `POST /pages/{id}/duplicate`, `PUT /profiles/{id}/pages-order` |
| Buttons | `POST /pages/{id}/buttons` (`kind`, `parentId`), `PATCH`/`DELETE /buttons/{id}`, `PUT /buttons/{id}/enabled`, `POST /buttons/{id}/duplicate`, `POST /buttons/{id}/move` (`{pageId, parentId}`), `PUT /pages/{id}/buttons-order` (`{ids, parentId}`) |
| Monitoring | `GET`/`PUT /monitoring` (interval, tile order and visibility), `GET /monitoring/live` (latest reading; polling keeps sampling alive ~6 s for the editor preview) |
| Desktop | `GET /health`, `GET /server`, `GET /server/wait?since=` (long poll), `POST /server/start\|stop\|restart`, `POST /shutdown`, `GET`/`PUT /app-settings`, `GET /logs`, `GET /logs/stream` (SSE), `GET /logs/file`, `POST /open`, `POST /backup`, `PATCH /devices/{id}`, `GET /system`, `GET /diagnostics` |
| Helpers | `POST /actions/test` (run an unsaved action on the PC), `POST /pick` (native file/folder dialog), `POST /app-info` (exe name and icon), `POST /icons` (PNG upload) |

All mutations go through `services/config.py` (`ConfigService`). It validates, writes in a
transaction, and tells the WebSocket hub to push a new `SNAPSHOT` to every device.

## 5. WebSocket protocol (v2)

Envelope: `{ "version": 1, "type": str, "requestId"?: str, "success"?: bool, "error"?: {code,message}, "payload": {} }`

Client → server: `HELLO {token, clientVersion}`, `ACTION_EXECUTE {buttonId}`, `PING`.
Server → client: `WELCOME {deviceId, serverName, protocolVersion}`, `SNAPSHOT {profile, pages, buttons, states}`,
`ACTION_RESULT`, `BUTTON_STATE {buttonId, state, detail}`, `CONFIG_CHANGED`, `DEVICE_CONNECTED`,
`DEVICE_DISCONNECTED`, `PONG`, `ERROR`.

Rules: unknown `type` → `ERROR{code:"unknown_type"}` (never disconnect); version mismatch → `ERROR` + close 4002;
no valid `HELLO` within 5 s → close 4001. Full spec: `docs/PROTOCOL.md`.

## 6. Action system

```text
actions/
  base.py        Action contract: type, display_name, description, category, icon, status,
                 config_model (Pydantic; also generates the editor form), execute(),
                 optional read_state(), requires_confirmation(), trusted_only, destructive
  registry.py    ActionRegistry + ordered CATEGORIES; catalog() feeds the editor menu
  engine.py      ActionEngine: load button -> check enabled/status -> validate config ->
                 confirmation check -> execute -> structured ActionError; run_step() for nesting
  runtime.py     ActionRuntime given to actions: persistent store, run_step, navigate,
                 refresh_state, shared services (audio)
  builtin/       launch (Open), system, audio, keys (Keyboard + Media), display, windows
                 (Window + Applications), navigation, workflow, streaming (coming soon), advanced
native/windows/  ctypes only: shell, power, audio (Core Audio COM), keyboard (SendInput),
                 winmgmt (windows/processes), display (DDC/CI, WMI, SetDisplayConfig, HDR)
services/audio.py        AudioService: COM on one dedicated thread; actions never touch COM
services/state_coordinator.py  reads action state after presses/config changes, polls only
                         "polled" actions every 2 s and only while a device is connected
integrations/obs.py      ObsIntegration: obs-websocket v5 client (challenge auth, request/response,
                         events), reconnect with backoff (1-30 s; stops on wrong password), a small
                         mirror of OBS state updated from events; OBS keys refresh on events only
services/obs_settings.py  OBS settings in the settings table, password encrypted with DPAPI
```

The same executor can appear under several menu categories through subclasses with their own
ids (`nav_open_url` reuses `open_url`, `media_volume_up` reuses `volume_up`), so stored buttons
keep a stable id while code is shared.

Composite actions (Multi Action, Toggle) store steps as `{actionType, actionConfig}`. Each
step is validated against the registry when saved (composites cannot nest) and runs through
`ActionEngine.run_step`, exactly like a button press.

Runtime state that must survive restarts (toggle on/off, counter values, timers) lives in the
`runtime_state` table (migration 0003), keyed `toggle:<button>`, `counter:<name>`, `timer:<name>`.

## 7. Security model

- The remote server binds `0.0.0.0` on a LAN port (or `127.0.0.1` if configured); the installer's
  firewall rule allows `OpenDeck.exe` on Private networks only.
- The engine's control listener and the host's endpoint bind `127.0.0.1` only; the host endpoint
  also requires a random per-run token.
- Requests from non-private (public) source IPs are rejected.
- **Pairing**: localhost editor shows a 6-digit code (single-use, 5-min TTL, rate-limited).
  iPad submits code → server issues a random 256-bit device token; only its SHA-256 hash is stored.
- Every WS session must `HELLO` with a valid, non-revoked token.
- Editor/admin REST endpoints accept loopback clients only.
- Clients can only reference stored `buttonId`s; no command text crosses the network.

## 8. State management

Backend `StateManager` keeps `buttonId → ButtonState` in memory. State providers (process
detector, volume, OBS later) push changes; only diffs are broadcast as `BUTTON_STATE`.
Process detection polls one `CreateToolhelp32Snapshot` every 2 s only while some button
needs it (M4). Snapshot on (re)connect gives clients the full truth.

Frontend: one `useSyncExternalStore` store fed by the WS client. Local press feedback is
immediate (CSS `:active` + `pending` state); server outcome sets `success`/`error` flash.

Folder navigation is device-local state: `DeckStore.folderStack` (outermost first) on top of the
active page. Opening a folder pushes a browser history entry (`history.state.msd`), so the
browser Back button leaves folders without a reload; the in-app Back key uses the same entry
when it owns it, and works without history support. A new `SNAPSHOT` keeps the longest still-
valid prefix of the stack; changing page or profile clears it. Nothing is sent to the PC.

## 8a. System Monitoring

A page with `kind = 'monitor'` shows live readings instead of keys. One page is added once
(`seeded_monitor_v1`) to the profile devices open first; users can delete it or add more from
a profile's menu. Monitor pages refuse buttons (`NOT_A_DECK_PAGE`).

```text
MonitoringService (services/monitoring.py)  one per PC
  ├─ Sampler — one worker thread; COM/PDH/wlanapi handles live there
  │    fast (every interval)  CPU, RAM, GPU usage, network rate
  │    slow (every 5 s)       GPU temp, CPU temp, drives + disk temp, battery, Wi-Fi, Internet
  └─ loop — runs only while a device shows a monitor page (MONITOR_SUBSCRIBE) or the editor
           preview polls; sends SYSTEM_MONITOR only when values change, plus a 5 s keep-alive
```

Windows sources (all ctypes, no extra dependencies, no administrator rights):

| Metric | Source |
|---|---|
| CPU usage | `GetSystemTimes` deltas |
| RAM | `GlobalMemoryStatusEx` |
| GPU usage | PDH `\GPU Engine(*)\Utilization Percentage` per adapter LUID, busiest engine type (as Task Manager) |
| GPU temperature | `D3DKMTQueryAdapterInfo(KMTQAITYPE_ADAPTERPERFDATA)` (WDDM 2.4+, vendor-neutral) |
| CPU temperature | LibreHardwareMonitor's local web server (`127.0.0.1:8085/data.json`) when running; otherwise N/A. The ACPI thermal zone is not used: on many boards it is a fixed placeholder (27.85 °C here). |
| Network | `GetBestInterfaceEx` (routing lookup, nothing sent) + `GetIfEntry2` byte counters of that interface only |
| Disk usage | `GetLogicalDrives`, fixed drives, `GetDiskFreeSpaceExW` |
| Disk temperature | `IOCTL_STORAGE_QUERY_PROPERTY(StorageDeviceTemperatureProperty)`, device opened with no access rights |
| Battery | `GetSystemPowerStatus` (no battery = `unsupported`) |
| Wi-Fi | `wlanapi` current connection (SSID/signal may be withheld without location permission) |
| Internet | `INetworkListManager::GetConnectivity` (Windows NCSI); we send no requests |

Each metric carries a `status` (`ok`, `unavailable`, `unsupported`, `error`, `unknown`); a
failing reader returns `error` for itself only. Readings are never written to SQLite; only
settings (`settings.monitoring`). Measured cost on the dev PC: ~0.3 % of one core and ~2 MB
at a 1 s interval while watched; nothing while nobody watches.

## 9. Frontend components

```text
App
├─ PairingScreen          (no token / token rejected)
└─ Dashboard
   ├─ DeckHeader          profile switch, page › folder trail, Back, PC name, connection pill
   ├─ DeckGrid            one grid for pages and folders; generated Back key inside folders
   │   └─ DeckKey         icon, label, state badge, press/pending/result, folder chevron
   ├─ MonitorGrid         System Monitoring readouts (monitor pages), same grid engine
   ├─ PageBar             page tabs (≥ 48 px targets)
   └─ OrientationNotice   portrait hint
Editor (/editor, lazy-loaded, localhost only)
├─ Sidebar               profile tree, pages, folders of the open page, drag reorder, menus
├─ PageCanvas            breadcrumbs, tiles of one container, drag reorder, drag into folders
│                        or onto a breadcrumb, ⋯ / right-click / long-press menus, Move to…
├─ ButtonDialog          Action/Folder type, preview, schema-driven ActionFields, IconPicker, test
├─ MonitorCanvas         monitor page: live preview, interval, tile order/visibility
└─ HostPage              address, pairing code, paired devices
```

## 9a. Responsive layout and UI modes

The dashboard has two modes with independent responsive rules:

- **Control mode** (built): rapid use, minimal chrome, maximum key area.
- **Editor mode** (built in M2): configuration of profiles, pages and buttons with drag and drop.

**Logical vs visual grid.** A page stores each key's logical position as `sort_order`. Control mode
reflows keys into a visual grid chosen for the space actually available
(`frontend/src/layout/gridLayout.ts`). The database is never changed by reflow, and there are no
per-device page configurations. The editor edits only the order (`sort_order`); its tile
grid simply wraps to the editor window.

**Layout engine.** Pure function, unit tested:

1. Size class from real viewport dimensions (no user-agent sniffing): `compact` when the
   shortest side is under 600 px (phones), `wide` from 1400 px wide (desktops), otherwise
   `regular` (tablets, laptops). Each class has min/max/comfortable key sizes and a gap.
2. For every column count, compute the largest square key that fits both width and height.
3. Among layouts within 6 % of the largest key, pick the lowest cost:
   mostly-empty last row (heavy penalty) + mismatch between grid shape and available area.
4. If nothing fits at the minimum key size, use comfortable-size columns and scroll
   vertically. Horizontal scrolling is never used.

The grid frame is measured with `ResizeObserver`; the viewport via `visualViewport`, `resize` and
`orientationchange`, so rotation and browser-chrome changes re-layout immediately. Key internals
(icon, label, status, insets) scale from the computed key size through the `--key` CSS variable.
The page bar falls back to a previous/next stepper with a native picker when tabs do not fit.
Heights use `100dvh` (with `100vh` fallback) and safe-area insets.

## 10. Milestones

1. **M1** backend, SQLite + migrations, WebSocket protocol, pairing, dashboard, Lock Windows.
2. **M2** profiles, pages, buttons, editor, icons, launch app, URL, file, folder.
3. **Action system** 71 actions incl. audio, media, keyboard, display, window, apps, workflow, OBS.
4. **Folders** nested button containers; **System Monitoring** live PC readings.
5. **1.0 desktop app** window, tray, server control, logs, settings, installer.
6. Next: generic button state + variables (monitoring values usable by buttons and automations).
