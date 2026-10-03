"""Logging: rotating files on disk plus a small in-memory buffer for the live log viewer.

Files (in the logs folder, rotated at 2 MB, 5 old files kept):
    server.log    the engine: server, devices, actions, monitoring, OBS
    desktop.log   the desktop app: window, tray, engine supervision

Each line: timestamp, level, component, message (and a traceback for exceptions).
The component is the logger name without the package prefix, e.g. "server.ws".
Secrets (pairing tokens, OBS password) are never passed to the logger.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from collections import deque
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-8s %(component)s: %(message)s"
MAX_BYTES = 2_000_000
BACKUP_COUNT = 5
BUFFER_SIZE = 2000
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class _ComponentFilter(logging.Filter):
    """Adds `component`: the logger name without the "opendeck." prefix."""

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if name.startswith("opendeck."):
            name = name[len("opendeck."):]
        elif name.startswith("uvicorn"):
            name = "http"  # uvicorn's own messages: listening, startup, shutdown
        record.component = name
        return True


@dataclass(frozen=True)
class LogEntry:
    seq: int
    time: float
    level: str
    component: str
    message: str

    def to_wire(self) -> dict:
        return {"seq": self.seq, "time": self.time, "level": self.level, "component": self.component,
                "message": self.message}


class LogBuffer(logging.Handler):
    """Last BUFFER_SIZE records in memory, numbered, with async listeners for live streaming."""

    def __init__(self, size: int = BUFFER_SIZE) -> None:
        super().__init__()
        self._entries: deque[LogEntry] = deque(maxlen=size)
        self._seq = 0
        self._lock = threading.Lock()
        self._listeners: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self.addFilter(_ComponentFilter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + logging.Formatter().formatException(record.exc_info)
        except Exception:
            message = str(record.msg)
        with self._lock:
            self._seq += 1
            entry = LogEntry(self._seq, record.created, record.levelname, getattr(record, "component", record.name),
                             message)
            self._entries.append(entry)
            listeners = list(self._listeners)
        for loop, queue in listeners:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, entry)
            except RuntimeError:
                pass  # loop closed

    def since(self, seq: int = 0, limit: int = 500) -> list[LogEntry]:
        with self._lock:
            entries = [e for e in self._entries if e.seq > seq]
        return entries[-limit:]

    def listen(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._listeners.add((asyncio.get_running_loop(), queue))
        return queue

    def unlisten(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._listeners = {(l, q) for l, q in self._listeners if q is not queue}


buffer = LogBuffer()


def configure_logging(log_dir: Path, *, file_name: str = "server.log", console: bool = True,
                      level: int | str = logging.INFO) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    component = _ComponentFilter()
    formatter = logging.Formatter(_FORMAT)
    file_handler = RotatingFileHandler(log_dir / file_name, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                                       encoding="utf-8", delay=True)
    file_handler.addFilter(component)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(buffer)

    # pythonw.exe / the packaged app have no console; only attach one when it exists.
    if console and sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.addFilter(component)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    # Uvicorn access logs are noisy (static assets); keep errors only unless diagnosing.
    if os.environ.get("OPENDECK_ACCESS_LOG") != "1":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def set_level(level: str) -> None:
    if level in LEVELS:
        logging.getLogger().setLevel(level)


def tail(path: Path, max_lines: int = 500, max_bytes: int = 512_000) -> list[str]:
    """Last lines of a log file without reading the whole file."""
    if not path.exists():
        return []
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]  # first line is probably cut
    return lines[-max_lines:]
