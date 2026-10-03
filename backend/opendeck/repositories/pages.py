from __future__ import annotations

import sqlite3

from ..db import Database
from ..db.database import utc_now
from ..models import Page
from ._ordering import renumber


def _page(row: sqlite3.Row) -> Page:
    return Page(
        id=row["id"], profile_id=row["profile_id"], name=row["name"],
        icon_ref=row["icon_ref"], sort_order=row["sort_order"], kind=row["kind"],
    )


class PageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_all(self) -> list[Page]:
        rows = self._db.query(
            "SELECT pages.* FROM pages JOIN profiles ON profiles.id = pages.profile_id"
            " ORDER BY profiles.sort_order, pages.sort_order, pages.name"
        )
        return [_page(r) for r in rows]

    def list_pages(self, profile_id: str) -> list[Page]:
        rows = self._db.query(
            "SELECT * FROM pages WHERE profile_id = ? ORDER BY sort_order, name", (profile_id,)
        )
        return [_page(r) for r in rows]

    def get(self, page_id: str) -> Page | None:
        row = self._db.query_one("SELECT * FROM pages WHERE id = ?", (page_id,))
        return _page(row) if row else None

    def create(self, page: Page) -> None:
        now = utc_now()
        self._db.execute(
            "INSERT INTO pages(id, profile_id, name, icon_ref, sort_order, kind, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (page.id, page.profile_id, page.name, page.icon_ref, page.sort_order, page.kind, now, now),
        )

    def update(self, page: Page) -> None:
        self._db.execute(
            "UPDATE pages SET name = ?, icon_ref = ?, updated_at = ? WHERE id = ?",
            (page.name, page.icon_ref, utc_now(), page.id),
        )

    def delete(self, page_id: str) -> bool:
        page = self.get(page_id)
        if page is None:
            return False
        with self._db.transaction():
            self._db.execute("DELETE FROM pages WHERE id = ?", (page_id,))
            self.normalize_order(page.profile_id)
        return True

    def next_sort_order(self, profile_id: str) -> int:
        row = self._db.query_one(
            "SELECT COALESCE(MAX(sort_order) + 1, 0) AS n FROM pages WHERE profile_id = ?",
            (profile_id,),
        )
        return int(row["n"])

    def reorder(self, ordered_ids: list[str]) -> None:
        renumber(self._db, "pages", ordered_ids)

    def normalize_order(self, profile_id: str) -> None:
        renumber(self._db, "pages", [p.id for p in self.list_pages(profile_id)])
