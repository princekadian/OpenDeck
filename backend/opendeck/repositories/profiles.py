from __future__ import annotations

import sqlite3

from ..db import Database
from ..db.database import utc_now
from ..models import Profile
from ._ordering import renumber


def _profile(row: sqlite3.Row) -> Profile:
    return Profile(
        id=row["id"], name=row["name"], description=row["description"],
        icon_ref=row["icon_ref"], sort_order=row["sort_order"],
    )


class ProfileRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[Profile]:
        return [_profile(r) for r in self._db.query("SELECT * FROM profiles ORDER BY sort_order, name")]

    def get(self, profile_id: str) -> Profile | None:
        row = self._db.query_one("SELECT * FROM profiles WHERE id = ?", (profile_id,))
        return _profile(row) if row else None

    def create(self, profile: Profile) -> None:
        now = utc_now()
        self._db.execute(
            "INSERT INTO profiles(id, name, description, icon_ref, sort_order, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile.id, profile.name, profile.description, profile.icon_ref, profile.sort_order,
             now, now),
        )

    def update(self, profile: Profile) -> None:
        self._db.execute(
            "UPDATE profiles SET name = ?, description = ?, icon_ref = ?, updated_at = ? WHERE id = ?",
            (profile.name, profile.description, profile.icon_ref, utc_now(), profile.id),
        )

    def delete(self, profile_id: str) -> bool:
        with self._db.transaction():
            deleted = self._db.execute("DELETE FROM profiles WHERE id = ?", (profile_id,)) > 0
            self.normalize_order()
        return deleted

    def next_sort_order(self) -> int:
        row = self._db.query_one("SELECT COALESCE(MAX(sort_order) + 1, 0) AS n FROM profiles")
        return int(row["n"])

    def reorder(self, ordered_ids: list[str]) -> None:
        renumber(self._db, "profiles", ordered_ids)

    def normalize_order(self) -> None:
        renumber(self._db, "profiles", [p.id for p in self.list()])
