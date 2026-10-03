from __future__ import annotations

import sqlite3

from ..db import Database
from ..db.database import utc_now
from ..models import Device


def _device(row: sqlite3.Row) -> Device:
    return Device(
        id=row["id"], name=row["name"], paired_at=row["paired_at"],
        last_seen_at=row["last_seen_at"], revoked=bool(row["revoked"]),
    )


class DeviceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, device_id: str, name: str, token_hash: str) -> Device:
        now = utc_now()
        self._db.execute(
            "INSERT INTO devices(id, name, token_hash, paired_at) VALUES (?, ?, ?, ?)",
            (device_id, name, token_hash, now),
        )
        return Device(id=device_id, name=name, paired_at=now)

    def find_active_by_token_hash(self, token_hash: str) -> Device | None:
        row = self._db.query_one(
            "SELECT * FROM devices WHERE token_hash = ? AND revoked = 0", (token_hash,)
        )
        return _device(row) if row else None

    def list(self) -> list[Device]:
        return [_device(r) for r in self._db.query("SELECT * FROM devices ORDER BY paired_at")]

    def touch(self, device_id: str) -> None:
        self._db.execute("UPDATE devices SET last_seen_at = ? WHERE id = ?", (utc_now(), device_id))

    def rename(self, device_id: str, name: str) -> bool:
        return self._db.execute("UPDATE devices SET name = ? WHERE id = ?", (name, device_id)) > 0

    def revoke(self, device_id: str) -> bool:
        return self._db.execute("UPDATE devices SET revoked = 1 WHERE id = ?", (device_id,)) > 0
