"""Starts, watches and stops the engine process for the desktop app.

- One engine at a time; it listens on a private 127.0.0.1 port chosen here.
- "running" only after its health endpoint answers (never earlier).
- An exit we didn't ask for is a crash: logged with the exit code, reported, restartable.
- Stop asks the engine to shut down over HTTP (it closes device connections, stops
  monitoring and closes the database), waits, and only then forces it.
- Engine console output (e.g. an import error before logging starts) goes to
  logs/engine-console.log so even early failures leave a trace.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

EngineState = Literal["stopped", "starting", "running", "stopping", "crashed"]
HEALTH_TIMEOUT_S = 40.0
STOP_TIMEOUT_S = 12.0
CREATE_NO_WINDOW = 0x08000000


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_json(method: str, url: str, body: Any = None, timeout: float = 5.0) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


class EngineSupervisor:
    def __init__(self, command: Callable[[int], list[str]], log_dir: Path,
                 on_change: Callable[["EngineSupervisor"], None] = lambda s: None,
                 job: Any = None, env: dict[str, str] | None = None) -> None:
        self._command = command  # control port -> argv
        self._log_dir = log_dir
        self._on_change = on_change
        self._job = job
        self._env = env
        self._lock = threading.RLock()
        self.state: EngineState = "stopped"
        self.error: str | None = None
        self.port: int | None = None
        self.process: subprocess.Popen | None = None
        self.started_at: float | None = None
        self._expect_exit = False

    @property
    def base_url(self) -> str | None:
        return f"http://127.0.0.1:{self.port}" if self.port else None

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process and self.process.poll() is None else None

    def _set(self, state: EngineState, error: str | None = None) -> None:
        self.state, self.error = state, error
        try:
            self._on_change(self)
        except Exception:
            log.exception("Engine state listener failed")

    # ---- lifecycle ----------------------------------------------------------------------

    def start(self) -> bool:
        with self._lock:
            if self.state in ("running", "starting") and self.pid:
                return True  # never two engines
            self.port = free_port()
            argv = self._command(self.port)
            self._log_dir.mkdir(parents=True, exist_ok=True)
            console = open(self._log_dir / "engine-console.log", "ab")
            self._expect_exit = False
            self._set("starting")
            log.info("Starting engine on 127.0.0.1:%d", self.port)
            try:
                self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=console, stderr=console,
                                                creationflags=CREATE_NO_WINDOW, env=self._env)
            except OSError as exc:
                console.close()
                log.error("Could not start the engine: %s", exc)
                self._set("crashed", f"Could not start the engine: {exc}")
                return False
            console.close()  # the child keeps its own handle
            if self._job is not None:
                self._job.add(self.process)
            process = self.process
        threading.Thread(target=self._watch, args=(process,), name="engine-watch", daemon=True).start()

        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False  # _watch reports the crash
            try:
                health = http_json("GET", f"{self.base_url}/api/admin/health", timeout=2)
                if health and health.get("ok"):
                    with self._lock:
                        if self.process is process:
                            self.started_at = time.time()
                            log.info("Engine running (pid %d, version %s)", process.pid, health.get("version"))
                            self._set("running")
                    return True
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.15)
        log.error("Engine did not become healthy within %ss; stopping it", HEALTH_TIMEOUT_S)
        self._kill(process)
        self._set("crashed", "The engine did not start in time. See the logs for details.")
        return False

    def _watch(self, process: subprocess.Popen) -> None:
        code = process.wait()
        with self._lock:
            if self.process is not process:
                return
            self.process = None
            self.started_at = None
            if self._expect_exit:
                log.info("Engine exited (code %s)", code)
                self._set("stopped")
            else:
                log.error("Engine stopped unexpectedly (exit code %s)", code)
                self._set("crashed", f"The engine stopped unexpectedly (exit code {code}). See the logs for details.")

    def stop(self) -> None:
        with self._lock:
            process = self.process
            if process is None or process.poll() is not None:
                self._set("stopped")
                return
            self._expect_exit = True
            self._set("stopping")
        log.info("Stopping engine (pid %d)", process.pid)
        try:
            http_json("POST", f"{self.base_url}/api/admin/shutdown", timeout=3)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("Engine did not accept the shutdown request: %s", exc)
        try:
            process.wait(STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            log.warning("Engine did not stop within %ss; terminating it", STOP_TIMEOUT_S)
            self._kill(process)
        # _watch moves the state to "stopped"; wait for it so callers see a settled state.
        for _ in range(50):
            if self.state == "stopped":
                break
            time.sleep(0.02)

    def restart(self) -> bool:
        self.stop()
        return self.start()

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        try:
            process.terminate()
            process.wait(5)
        except Exception:
            pass

    def call(self, method: str, path: str, body: Any = None, timeout: float = 5.0) -> Any:
        """Engine admin API call; raises if the engine isn't running."""
        if self.state != "running" or not self.base_url:
            raise ConnectionError("The engine is not running.")
        return http_json(method, f"{self.base_url}{path}", body, timeout)
