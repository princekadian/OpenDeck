# Development

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements-dev.txt
cd frontend
npm install
npm run build        # the engine serves frontend\dist
```

## Run

```powershell
cd backend
..\.venv\Scripts\python -m opendeck.desktop          # desktop app: window + tray + engine
..\.venv\Scripts\python -m opendeck.desktop --minimized
..\.venv\Scripts\python -m opendeck.desktop --exit   # ask a running copy to quit
..\.venv\Scripts\python -m opendeck                  # server only (headless), Ctrl+C to stop
```

Frontend live reload (against a headless server on :8765):

```powershell
cd frontend; npm run dev     # http://localhost:5173 (/editor, /desktop), proxies /api and /ws
```

Environment variables (development and tests):

| Variable | Default | Purpose |
|---|---|---|
| `OPENDECK_DATA_DIR` | `%LOCALAPPDATA%\OpenDeck` | user-data root; a non-default folder never imports MyStreamDeck data |
| `OPENDECK_PORT` | saved setting (8765) | pins the remote-control port |
| `OPENDECK_STATIC_DIR` | `frontend\dist` | built frontend |
| `OPENDECK_ACCESS_LOG` | off | `1` logs every HTTP request |

Use a separate `OPENDECK_DATA_DIR` when experimenting, so your real configuration is not touched.

## Tests

```powershell
cd backend;  ..\.venv\Scripts\python -m pytest -q
cd frontend; npm test; npm run typecheck
```

Backend tests include a live end-to-end WebSocket test, an engine **process** test (health, server,
clean shutdown), the remote-server lifecycle (start/stop/restart, port conflict), the supervisor
with a fake engine (crash detection, restart, clean stop), log rotation, data import from the
old MyStreamDeck folders, and the start-with-Windows registry value (against a test key, never the real Run
key). Tests replace Lock with a recorder and never send keystrokes or open windows.

## Code map

```text
backend/opendeck/
  engine.py            engine process: one app, private control listener, remote server
  server/remote.py     remote-control server (start/stop/restart, states, long poll)
  server/desktop_api.py  health, server control, settings, logs (SSE), devices, diagnostics
  desktop/host.py      desktop app: tray, single instance, window process, control endpoint
  desktop/supervisor.py  engine process supervision
  desktop/tray.py      Shell_NotifyIcon tray (ctypes)
  desktop/ui.py        WebView2 window (pywebview) and its JS bridge
  desktop/winapi.py    mutex, events, job object, window focus
  logging_setup.py     rotating files + in-memory buffer for the live log viewer
  config.py            data folders, import from MyStreamDeck
frontend/src/
  desktop/             desktop app UI (dashboard, settings, logs, devices, diagnostics)
  editor/              editor (also used embedded in the desktop app)
  dashboard/           device control surface
```

Windows integration uses `ctypes` only (no pywin32). Keep new native code in `native/windows/` or
`desktop/winapi.py`.

## Measured resource use (1.0, packaged, this developer PC)

Windows 11, Python 3.12 build. Working-set numbers from Task Manager-equivalent counters.

| Situation | Processes | Memory | CPU |
|---|---|---|---|
| Server running, window closed (tray) | desktop + engine | ~100 MB | ~0.05 % of one core idle (30 s sample) |
| Window open | + window process | + ~106 MB, plus WebView2 (6 processes, ~340 MB summed working set, which double-counts shared pages) | — |
| Startup to server listening | | | ~3 s |
| `--exit` to all processes gone | | | ~1.2 s |

The window uses the same Chromium engine as a browser tab, so with the window open the cost is
similar to the old workflow of keeping `/editor` open in Edge. The difference is that closing the
window ends its process and WebView2 entirely; the old workflow needed a browser kept open.
Monitoring adds ~0.3 % of one core at a 1 s interval only while someone watches it.
