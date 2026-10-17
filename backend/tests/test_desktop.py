"""Desktop app support: server lifecycle, engine process, settings, logs, data import, supervision."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sqlite3
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opendeck import __version__, logging_setup
from opendeck.config import AppConfig, adopt_legacy_data
from opendeck.server.http import create_app
from opendeck.server.remote import RemoteServer

BACKEND = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, timeout: float = 3) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


# ---- remote server ------------------------------------------------------------------------------

def test_remote_server_start_stop_restart_and_port_conflict(services) -> None:
    app = create_app(services)
    port = free_port()
    remote = RemoteServer(app, lambda: ("127.0.0.1", port))

    async def scenario():
        assert remote.info()["state"] == "stopped"
        info = await remote.start()
        assert info["state"] == "running" and info["lanOnly"] is False
        assert await asyncio.to_thread(get, f"http://127.0.0.1:{port}/api/info")
        version = remote.version
        waiter = asyncio.create_task(remote.wait_change(version, 5))
        assert (await remote.stop())["state"] == "stopped"
        assert await waiter != version  # long poll woke up on the change
        with pytest.raises(OSError):
            await asyncio.to_thread(get, f"http://127.0.0.1:{port}/api/info", 1)

        blocker = socket.socket()
        blocker.bind(("127.0.0.1", port))
        blocker.listen()
        try:
            info = await remote.start()
            assert info["state"] == "error" and f"Port {port} is already in use" in info["error"]
        finally:
            blocker.close()
        assert (await remote.restart())["state"] == "running"
        await remote.stop()

    asyncio.run(scenario())


# ---- engine process --------------------------------------------------------------------------

def test_engine_process_lifecycle(tmp_path) -> None:
    control, lan = free_port(), free_port()
    env = {**os.environ, "OPENDECK_DATA_DIR": str(tmp_path), "OPENDECK_PORT": str(lan), "PYTHONUTF8": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "opendeck", "--engine", "--control-port", str(control)],
                            cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{control}/api/admin"
        for _ in range(150):
            try:
                health = get(f"{base}/health")
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("engine never became healthy")
        assert health["ok"] and health["database"]["schemaVersion"] >= 5
        assert get(f"{base}/server")["state"] == "running"  # auto-start is on by default
        assert get(f"http://127.0.0.1:{lan}/api/info")["productName"]
        request = urllib.request.Request(f"{base}/shutdown", method="POST")
        urllib.request.urlopen(request, timeout=3).read()
        assert proc.wait(15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    log = (tmp_path / "logs" / "server.log").read_text(encoding="utf-8")
    assert "Engine ready" in log and "Engine stopped" in log
    assert (tmp_path / "data" / "data.sqlite3").exists()


# ---- settings, devices, logs API --------------------------------------------------------------------

@pytest.fixture
def desktop_client(services):
    services.remote = RemoteServer(create_app(services), lambda: ("127.0.0.1", free_port()))
    return TestClient(create_app(services))


def test_app_settings_persist_and_validate(desktop_client, services) -> None:
    view = desktop_client.get("/api/admin/app-settings").json()
    assert view["settings"]["serverPort"] == 8765 and view["settings"]["minimizeToTray"] is True
    body = {**view["settings"], "serverPort": 9123, "minimizeToTray": False, "logLevel": "WARNING"}
    body.pop("startWithWindows")
    saved = desktop_client.put("/api/admin/app-settings", json=body)
    assert saved.status_code == 200 and saved.json()["settings"]["serverPort"] == 9123
    from opendeck.services.app_settings import load_app_settings

    assert load_app_settings(services.settings).minimize_to_tray is False
    assert desktop_client.put("/api/admin/app-settings", json={**body, "serverPort": 80}).status_code == 422
    assert desktop_client.put("/api/admin/app-settings", json={**body, "preferredAddress": "nope"}).status_code == 422
    logging.getLogger().setLevel(logging.INFO)


def test_device_rename_and_status_fields(desktop_client, services) -> None:
    code, _ = services.pairing.current_code()
    device = desktop_client.post("/api/pair", json={"code": code, "deviceName": "iPad"}).json()
    assert desktop_client.patch(f"/api/admin/devices/{device['deviceId']}", json={"name": "Studio iPad"}).status_code == 200
    names = [d["name"] for d in desktop_client.get("/api/admin/status").json()["pairedDevices"]]
    assert names == ["Studio iPad"]
    assert desktop_client.patch("/api/admin/devices/missing", json={"name": "x"}).status_code == 404


def test_logs_endpoint_and_diagnostics(desktop_client) -> None:
    root = logging.getLogger()
    root.addHandler(logging_setup.buffer)
    try:
        logging.getLogger("opendeck.test").warning("hello from the test")
    finally:
        root.removeHandler(logging_setup.buffer)
    entries = desktop_client.get("/api/admin/logs").json()["entries"]
    mine = [e for e in entries if e["message"] == "hello from the test"]
    assert mine and mine[-1]["component"] == "test" and mine[-1]["level"] == "WARNING"
    after = mine[-1]["seq"]
    assert all(e["seq"] > after for e in desktop_client.get(f"/api/admin/logs?after={after}").json()["entries"])
    diag = desktop_client.get("/api/admin/diagnostics").json()
    assert diag["version"] == __version__ and diag["schemaVersion"] >= 5 and diag["databaseOk"] is True
    assert desktop_client.get("/api/admin/health").json()["ok"] is True


def test_log_files_rotate_and_tail_is_bounded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(logging_setup, "MAX_BYTES", 4000)
    root = logging.getLogger()
    saved = list(root.handlers), root.level
    try:
        logging_setup.configure_logging(tmp_path, file_name="server.log", console=False)
        log = logging.getLogger("opendeck.rotation")
        for i in range(400):
            log.info("line %04d %s", i, "x" * 40)
        for handler in root.handlers:
            handler.flush()
        files = sorted(p.name for p in tmp_path.iterdir())
        assert "server.log" in files and "server.log.1" in files
        assert len([f for f in files if f.startswith("server.log.")]) <= logging_setup.BACKUP_COUNT
        lines = logging_setup.tail(tmp_path / "server.log", max_lines=5)
        assert len(lines) == 5 and "line 0399" in lines[-1] and "rotation:" in lines[-1]
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if handler is not logging_setup.buffer:
                handler.close()
        for handler in saved[0]:
            root.addHandler(handler)
        root.setLevel(saved[1])


# ---- data import ---------------------------------------------------------------------------------

def test_existing_data_is_copied_once_and_original_kept(tmp_path) -> None:
    legacy = tmp_path / "Roaming" / "MyStreamDeck"
    (legacy / "assets").mkdir(parents=True)
    (legacy / "assets" / "icon.png").write_bytes(b"png")
    db = sqlite3.connect(legacy / "data.sqlite3")
    db.execute("CREATE TABLE t(x)")
    db.execute("INSERT INTO t VALUES (42)")
    db.commit()
    db.close()
    config = AppConfig(data_dir=tmp_path / "Local" / "OpenDeck")

    sources = [(tmp_path / "missing" / "data.sqlite3", tmp_path / "missing"),
               (legacy / "data.sqlite3", legacy / "assets")]
    assert adopt_legacy_data(config, sources) is True
    copied = sqlite3.connect(config.db_path)
    assert copied.execute("SELECT x FROM t").fetchone() == (42,)
    copied.close()
    assert (config.assets_dir / "icon.png").read_bytes() == b"png"
    assert (legacy / "data.sqlite3").exists() and (legacy / "assets" / "icon.png").exists()
    assert adopt_legacy_data(config, sources) is False  # never twice / never over new data


def test_backups_go_to_the_backup_folder(services) -> None:
    path = services.db.backup("manual-test")
    assert path.parent == services.config.backup_dir and path.exists()


# ---- supervisor ----------------------------------------------------------------------------------

FAKE_ENGINE = textwrap.dedent('''
    import json, sys, threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port = int(sys.argv[1])
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self._ok({"ok": True, "version": "test"})
        def do_POST(self):
            self._ok({"ok": True})
            if self.path.endswith("/shutdown"):
                threading.Thread(target=server.shutdown).start()
        def _ok(self, body):
            data = json.dumps(body).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)
        def log_message(self, *a): pass
    server = HTTPServer(("127.0.0.1", port), H)
    server.serve_forever()
''')


def test_supervisor_reports_running_crash_and_clean_stop(tmp_path) -> None:
    from opendeck.desktop.supervisor import EngineSupervisor

    script = tmp_path / "fake_engine.py"
    script.write_text(FAKE_ENGINE, encoding="utf-8")
    states: list[str] = []
    sup = EngineSupervisor(lambda port: [sys.executable, str(script), str(port)], tmp_path / "logs",
                           on_change=lambda s: states.append(s.state))
    assert sup.start() is True and sup.state == "running"
    assert sup.start() is True  # already running: no second engine
    pid = sup.pid
    sup.process.kill()  # simulate a crash
    for _ in range(100):
        if sup.state == "crashed":
            break
        time.sleep(0.05)
    assert sup.state == "crashed" and "unexpectedly" in (sup.error or "")
    assert sup.restart() is True and sup.pid != pid
    sup.stop()
    assert sup.state == "stopped" and sup.pid is None
    assert states[:2] == ["starting", "running"] and "crashed" in states and states[-1] == "stopped"


def test_supervisor_reports_engine_that_dies_at_start(tmp_path) -> None:
    from opendeck.desktop.supervisor import EngineSupervisor

    sup = EngineSupervisor(lambda port: [sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path / "logs")
    assert sup.start() is False
    for _ in range(100):
        if sup.state == "crashed":
            break
        time.sleep(0.05)
    assert sup.state == "crashed" and "exit code 3" in (sup.error or "")


# ---- start with Windows ------------------------------------------------------------------------

def test_start_with_windows_uses_a_reversible_run_value(monkeypatch) -> None:
    import winreg

    from opendeck.native.windows import startup

    test_key = r"Software\OpenDeckTests\Run"  # never the real Run key
    monkeypatch.setattr(startup, "RUN_KEY", test_key)
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, test_key).Close()
    try:
        with pytest.raises(RuntimeError):  # from source there is no installed exe to register
            startup.set_enabled(True)
        monkeypatch.setattr(startup, "executable", lambda: Path(r"C:\Program Files\OpenDeck\OpenDeck.exe"))
        startup.set_enabled(True)
        assert startup.is_enabled()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, test_key) as key:
            assert winreg.QueryValueEx(key, startup.VALUE_NAME)[0].endswith('OpenDeck.exe" --minimized')
        startup.set_enabled(False)
        assert not startup.is_enabled()
        startup.set_enabled(False)  # idempotent
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, test_key)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\OpenDeckTests")


def test_window_arguments_survive_tokens_that_start_with_a_dash() -> None:
    """A random token like "-abc" must not be mistaken for an option (the window then refused to open)."""
    from opendeck.desktop import host, ui

    argv = host.ui_command("http://127.0.0.1:5000", "-Xy_z", "")
    parsed = ui.build_parser().parse_known_args(argv[argv.index("--ui"):])[0]
    assert parsed.token == "-Xy_z" and parsed.host_url == "http://127.0.0.1:5000" and parsed.view == ""
