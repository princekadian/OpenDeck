"""SQLite connection management and forward-only migrations."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Single shared connection guarded by a lock.

    Workload is tiny (a handful of writes per minute), so one connection with
    WAL mode is simpler and lighter than a pool.
    """

    def __init__(self, path: Path, backup_dir: Path | None = None) -> None:
        self.path = path
        # Copies made before migrations and on request; defaults to next to the database.
        self.backup_dir = backup_dir or path.parent
        self._lock = threading.RLock()
        self._depth = 0
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=3000")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Atomic unit of work. Nested calls join the outermost transaction."""
        with self._lock:
            if self._depth:
                self._depth += 1
                try:
                    yield self._conn
                finally:
                    self._depth -= 1
                return
            self._conn.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")
            finally:
                self._depth = 0

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        """Run a single write statement; returns affected row count."""
        with self.transaction() as conn:
            return conn.execute(sql, params).rowcount

    # ---- migrations -------------------------------------------------------

    def migrate(self, up_to: int | None = None) -> list[int]:
        """Apply pending migrations in order. Returns applied version numbers.

        `up_to` stops at a given version (used by migration tests).
        """
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {r[0] for r in self._conn.execute("SELECT version FROM schema_migrations")}
        pending = [(v, sql) for v, sql in _load_migrations()
                   if v not in applied and (up_to is None or v <= up_to)]
        if not pending:
            return []
        if applied:  # existing user data: back up before touching the schema
            self._backup(max(applied))
        for version, sql in pending:
            log.info("Applying database migration %04d", version)
            with self.transaction() as conn:
                for statement in _split_statements(sql):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
        return [v for v, _ in pending]

    def _backup(self, from_version: int) -> None:
        self.backup(f"v{from_version:04d}")

    def backup(self, label: str) -> Path:
        """Consistent copy of the database into the backup folder (SQLite online backup)."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = self.backup_dir / f"{self.path.stem}.{label}.bak"
        with self._lock:
            dest = sqlite3.connect(target)
            try:
                self._conn.backup(dest)
            finally:
                dest.close()
        log.info("Database backed up to %s", target)
        return target

    def schema_version(self) -> int:
        row = self.query_one("SELECT MAX(version) AS v FROM schema_migrations")
        return int(row["v"] or 0) if row else 0

    def healthy(self) -> bool:
        try:
            return self.query_one("PRAGMA quick_check")[0] == "ok"
        except Exception:
            return False


def _load_migrations() -> list[tuple[int, str]]:
    folder = resources.files(__package__).joinpath("migrations")
    found: list[tuple[int, str]] = []
    for entry in folder.iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:4].isdigit():
            found.append((int(name[:4]), entry.read_text(encoding="utf-8")))
    return sorted(found)


def _split_statements(sql: str) -> list[str]:
    # Migrations are plain DDL/DML: full-line `--` comments, no semicolons inside literals.
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in code.split(";") if s.strip()]
