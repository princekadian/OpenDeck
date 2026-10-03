"""Persistent key/value store for action runtime state (toggles, counters, timers)."""

from __future__ import annotations

import json
from typing import Any

from ..db import Database
from ..db.database import utc_now


class RuntimeStateStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, dict[str, Any] | None] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        if key not in self._cache:
            row = self._db.query_one("SELECT value FROM runtime_state WHERE key = ?", (key,))
            self._cache[key] = json.loads(row["value"]) if row else None
        value = self._cache[key]
        return dict(value) if value is not None else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), utc_now()),
        )
        self._cache[key] = dict(value)
