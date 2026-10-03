"""The desktop app: tray icon, engine supervision and the window, without a console.

Process model (all the same OpenDeck.exe):

    OpenDeck.exe            this host: tray, single instance, engine supervisor
     ├─ --engine --control-port N   the engine (server, actions, database, monitoring)
     └─ --ui --host-url ...         the window (WebView2), only while it is open

The host talks to the engine over the engine's admin API on 127.0.0.1, and the window
talks to the host over a tiny loopback HTTP endpoint protected by a random token.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__
from ..branding import PRODUCT_NAME
from ..config import AppConfig
from ..logging_setup import configure_logging
from . import winapi
from .supervisor import EngineSupervisor
from .tray import SEPARATOR, MenuItem, TrayIcon

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
STATE_LABELS = {"running": "Running", "stopped": "Stopped", "starting": "Starting…", "stopping": "Stopping…",
                "error": "Error", "crashed": "Engine stopped"}


def resource_dir() -> Path:
    """Bundled files (icons): next to the exe when packaged, the repository otherwise."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[3]


def engine_command(port: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--engine", "--control-port", str(port)]
    return [sys.executable, "-m", "opendeck", "--engine", "--control-port", str(port)]


def ui_command(host_url: str, token: str, view: str) -> list[str]:
    # "--name=value": a random token may start with "-", which argparse would read as an option.
    tail = ["--ui", f"--host-url={host_url}", f"--token={token}", f"--view={view}"]
    if getattr(sys, "frozen", False):
        return [sys.executable, *tail]
    return [sys.executable, "-m", "opendeck.desktop", *tail]


class DesktopApp:
    def __init__(self, minimized: bool) -> None:
        self.config = AppConfig.from_env()
        self.minimized = minimized
        self.exiting = threading.Event()
        self.token = secrets.token_urlsafe(24)
        self.ui: subprocess.Popen | None = None
        self.requested_view: str | None = None
        self.remote: dict = {"state": "stopped"}
        self._lock = threading.Lock()
        env = dict(os.environ)
        if not getattr(sys, "frozen", False):  # development: make `-m opendeck` importable
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get("PYTHONPATH", "")
        self.env = env
        self.job = winapi.KillOnCloseJob()
        self.engine = EngineSupervisor(engine_command, self.config.log_dir, self._engine_changed, self.job, env)
        icons = resource_dir() / "assets" / "icons"
        self.tray = TrayIcon({s: icons / f"tray-{s}.ico" for s in ("running", "stopped", "starting", "error")},
                             self._menu, on_open=lambda: self.open_window())
        self.control: ThreadingHTTPServer | None = None

    # ---- run ------------------------------------------------------------------------------

    def run(self) -> int:
        log.info("%s %s desktop app starting (pid %d)", PRODUCT_NAME, __version__, os.getpid())
        self.tray.start()
        self._start_control_server()
        threading.Thread(target=self._show_listener, name="show-event", daemon=True).start()
        threading.Thread(target=self._exit_listener, name="exit-event", daemon=True).start()
        threading.Thread(target=self._remote_watcher, name="server-watch", daemon=True).start()
        if not self.minimized:
            self.open_window()
        self.engine.start()
        self.exiting.wait()
        self._shutdown()
        return 0

    def _shutdown(self) -> None:
        log.info("Desktop app exiting")
        if self.ui and self.ui.poll() is None:
            self.ui.terminate()
        self.engine.stop()
        self.tray.stop()
        if self.control:
            self.control.shutdown()
        log.info("Desktop app stopped")

    def exit(self) -> None:
        self.exiting.set()

    # ---- window -----------------------------------------------------------------------------

    def open_window(self, view: str = "") -> None:
        with self._lock:
            if view:
                self.requested_view = view
            if self.ui and self.ui.poll() is None:
                winapi.bring_process_window_to_front(self.ui.pid)
                return
            host_url = f"http://127.0.0.1:{self.control.server_address[1]}" if self.control else ""
            self.ui = subprocess.Popen(ui_command(host_url, self.token, view), creationflags=CREATE_NO_WINDOW,
                                       env=self.env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=self._ui_log())
            self.job.add(self.ui)
            self.requested_view = None  # passed on the command line
            log.info("Window opened (pid %d)", self.ui.pid)
            threading.Thread(target=self._watch_ui, args=(self.ui,), daemon=True).start()

    def _ui_log(self):
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        return open(self.config.log_dir / "window-console.log", "ab")

    def _watch_ui(self, process: subprocess.Popen) -> None:
        code = process.wait()
        log.info("Window closed (exit code %s)", code)
        if self.exiting.is_set():
            return
        if code != 0:
            self.tray.notify(PRODUCT_NAME, "The window closed unexpectedly. Open it again from this icon.", error=True)
            return
        if not self._minimize_to_tray():
            self.exit()  # closing the window quits when "Keep running in the notification area" is off

    def _minimize_to_tray(self) -> bool:
        try:
            return bool(self.engine.call("GET", "/api/admin/app-settings")["settings"]["minimizeToTray"])
        except Exception:
            return True  # can't ask: keep running rather than silently stopping the server

    def _show_listener(self) -> None:
        event = winapi.ShowEvent()
        while not self.exiting.is_set():
            if event.wait(1000):
                self.open_window()

    def _exit_listener(self) -> None:
        event = winapi.ShowEvent(winapi.EXIT_EVENT_NAME)
        while not self.exiting.is_set():
            if event.wait(1000):
                log.info("Exit requested by another launch (--exit)")
                self.exit()

    # ---- engine and server state -------------------------------------------------------------

    def _engine_changed(self, engine: EngineSupervisor) -> None:
        if engine.state == "crashed":
            self.tray.notify(PRODUCT_NAME, engine.error or "The engine stopped unexpectedly.", error=True)
        self._refresh_tray()

    def _remote_watcher(self) -> None:
        version = 0
        while not self.exiting.is_set():
            if self.engine.state != "running":
                time.sleep(0.5)
                version = 0
                continue
            try:
                info = self.engine.call("GET", f"/api/admin/server/wait?since={version}", timeout=35)
            except Exception:
                time.sleep(1)
                continue
            previous = self.remote.get("state")
            self.remote, version = info, info.get("version", 0)
            if info.get("state") == "error" and previous != "error":
                self.tray.notify(PRODUCT_NAME, info.get("error") or "The server stopped.", error=True)
            self._refresh_tray()

    def tray_state(self) -> tuple[str, str]:
        engine = self.engine.state
        if engine == "crashed":
            return "error", "Engine stopped"
        if engine != "running":
            return "starting", STATE_LABELS.get(engine, engine)
        state = self.remote.get("state", "stopped")
        icon = {"running": "running", "error": "error", "stopped": "stopped"}.get(state, "starting")
        return icon, STATE_LABELS.get(state, state)

    def _refresh_tray(self) -> None:
        icon, label = self.tray_state()
        tip = f"{PRODUCT_NAME} — Server: {label}"
        urls = self.remote.get("urls") or []
        if self.remote.get("state") == "running" and urls:
            tip += f"\n{urls[0].removeprefix('http://')}"
        self.tray.set_state(icon, tip)

    def _menu(self) -> list[MenuItem]:
        _icon, label = self.tray_state()
        engine_up = self.engine.state == "running"
        server = self.remote.get("state")
        background = lambda fn: (lambda: threading.Thread(target=fn, daemon=True).start())  # noqa: E731
        items = [
            MenuItem(f"{PRODUCT_NAME} {__version__}"),
            MenuItem(f"Server: {label}"),
            SEPARATOR,
            MenuItem("Open OpenDeck", lambda: self.open_window(), default=True),
        ]
        if self.engine.state == "crashed":
            items.append(MenuItem("Restart engine", background(self.engine.restart)))
        items += [
            MenuItem("Start Server", background(lambda: self._server("start"))
                     if engine_up and server in ("stopped", "error") else None),
            MenuItem("Stop Server", background(lambda: self._server("stop")) if engine_up and server == "running" else None),
            MenuItem("Restart Server", background(lambda: self._server("restart")) if engine_up and server == "running" else None),
            MenuItem("Open Remote Dashboard", background(lambda: self._engine_post("/api/admin/open", {"target": "remote"}))
                     if engine_up and server == "running" else None),
            MenuItem("Open Logs", lambda: os.startfile(self.config.log_dir)),
            MenuItem("Settings", lambda: self.open_window("settings")),
            SEPARATOR,
            MenuItem("Exit", self.exit),
        ]
        return items

    def _server(self, command: str) -> None:
        self._engine_post(f"/api/admin/server/{command}", None)

    def _engine_post(self, path: str, body) -> None:
        try:
            self.engine.call("POST", path, body, timeout=30)
        except Exception as exc:
            log.warning("Request %s failed: %s", path, exc)

    # ---- control endpoint for the window ---------------------------------------------------------

    def state(self) -> dict:
        return {
            "engine": self.engine.state,
            "error": self.engine.error,
            "url": f"{self.engine.base_url}/desktop" if self.engine.base_url else None,
            "enginePid": self.engine.pid,
            "hostPid": os.getpid(),
            "uiPid": self.ui.pid if self.ui and self.ui.poll() is None else None,
            "version": __version__,
        }

    def command(self, name: str) -> dict:
        if name == "restart-engine":
            threading.Thread(target=self.engine.restart, daemon=True).start()
        elif name == "exit":
            threading.Timer(0.2, self.exit).start()  # answer the request first
        elif name == "open-logs":
            os.startfile(self.config.log_dir)
        else:
            return {"ok": False, "error": f"Unknown command {name}"}
        return {"ok": True}

    def _start_control_server(self) -> None:
        app = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorised(self) -> bool:
                if secrets.compare_digest(self.headers.get("X-Desktop-Token", ""), app.token):
                    return True
                self._reply(403, {"ok": False})
                return False

            def do_GET(self) -> None:  # noqa: N802
                if self._authorised():
                    self._reply(200, app.state()) if self.path == "/state" else self._reply(404, {})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorised():
                    return
                if self.path.startswith("/command/"):
                    self._reply(200, app.command(self.path.removeprefix("/command/")))
                elif self.path == "/take-view":
                    view, app.requested_view = app.requested_view, None
                    self._reply(200, {"view": view})
                else:
                    self._reply(404, {})

            def log_message(self, *args) -> None:  # keep the log quiet
                pass

        self.control = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.control.serve_forever, name="host-control", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PRODUCT_NAME)
    parser.add_argument("--minimized", action="store_true", help="start in the notification area")
    parser.add_argument("--exit", action="store_true", help="ask a running copy to quit cleanly")
    args, _ = parser.parse_known_args(argv)
    if args.exit:
        return 0 if winapi.signal_show(winapi.EXIT_EVENT_NAME) else 1

    config = AppConfig.from_env()
    configure_logging(config.log_dir, file_name="desktop.log", console=False)
    instance = winapi.SingleInstance()
    if not instance.first:
        log.info("Already running; asking the running copy to show its window")
        if not winapi.signal_show():
            winapi.message_box(f"{PRODUCT_NAME} is already running. Look for its icon in the notification area.",
                               PRODUCT_NAME)
        return 0
    try:
        return DesktopApp(minimized=args.minimized).run()
    except Exception:
        log.critical("Desktop app crashed", exc_info=True)
        winapi.message_box(f"{PRODUCT_NAME} hit an unexpected problem and has to close.\n\n"
                           f"Details are in {config.log_dir / 'desktop.log'}.", PRODUCT_NAME, error=True)
        return 1
    finally:
        instance.close()

