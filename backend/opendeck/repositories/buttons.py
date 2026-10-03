from __future__ import annotations

import json
import sqlite3

from ..db import Database
from ..db.database import utc_now
from ..models import Button
from ._ordering import renumber


def _button(row: sqlite3.Row) -> Button:
    return Button(
        id=row["id"], page_id=row["page_id"], parent_id=row["parent_id"], kind=row["kind"],
        sort_order=row["sort_order"], label=row["label"], description=row["description"],
        icon_ref=row["icon_ref"], action_type=row["action_type"],
        action_config=json.loads(row["action_config"]),
        appearance=json.loads(row["appearance"]),
        state_config=json.loads(row["state_config"]),
        enabled=bool(row["enabled"]),
    )


class ButtonRepository:
    """Buttons live in containers: a page (parent_id NULL) or a folder button."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, button_id: str) -> Button | None:
        row = self._db.query_one("SELECT * FROM buttons WHERE id = ?", (button_id,))
        return _button(row) if row else None

    def list_all(self) -> list[Button]:
        rows = self._db.query("SELECT * FROM buttons ORDER BY page_id, parent_id, sort_order")
        return [_button(r) for r in rows]

    def list_children(self, page_id: str, parent_id: str | None = None) -> list[Button]:
        """Buttons directly in one container, in order."""
        rows = self._db.query(
            "SELECT * FROM buttons WHERE page_id = ? AND parent_id IS ? ORDER BY sort_order",
            (page_id, parent_id),
        )
        return [_button(r) for r in rows]

    def list_for_page(self, page_id: str) -> list[Button]:
        """Top-level buttons of a page (not those inside folders)."""
        return self.list_children(page_id, None)

    def list_subtree(self, page_id: str) -> list[Button]:
        """Every button on a page, including inside folders."""
        rows = self._db.query("SELECT * FROM buttons WHERE page_id = ? ORDER BY sort_order", (page_id,))
        return [_button(r) for r in rows]

    def descendants(self, folder_id: str) -> list[Button]:
        rows = self._db.query(
            "WITH RECURSIVE tree(id) AS (SELECT id FROM buttons WHERE parent_id = ?"
            " UNION ALL SELECT b.id FROM buttons b JOIN tree t ON b.parent_id = t.id)"
            " SELECT buttons.* FROM buttons JOIN tree ON buttons.id = tree.id",
            (folder_id,),
        )
        return [_button(r) for r in rows]

    def list_for_profile(self, profile_id: str) -> list[Button]:
        rows = self._db.query(
            "SELECT b.* FROM buttons b JOIN pages p ON p.id = b.page_id"
            " WHERE p.profile_id = ? ORDER BY p.sort_order, b.parent_id, b.sort_order",
            (profile_id,),
        )
        return [_button(r) for r in rows]

    def create(self, button: Button) -> None:
        now = utc_now()
        self._db.execute(
            "INSERT INTO buttons(id, page_id, parent_id, kind, sort_order, label, description, icon_ref,"
            " action_type, action_config, appearance, state_config, enabled, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                button.id, button.page_id, button.parent_id, button.kind, button.sort_order, button.label,
                button.description, button.icon_ref, button.action_type, json.dumps(button.action_config),
                json.dumps(button.appearance), json.dumps(button.state_config),
                int(button.enabled), now, now,
            ),
        )

    def update(self, button: Button) -> None:
        self._db.execute(
            "UPDATE buttons SET page_id = ?, parent_id = ?, kind = ?, label = ?, description = ?,"
            " icon_ref = ?, action_type = ?, action_config = ?, appearance = ?, state_config = ?,"
            " enabled = ?, updated_at = ? WHERE id = ?",
            (
                button.page_id, button.parent_id, button.kind, button.label, button.description,
                button.icon_ref, button.action_type, json.dumps(button.action_config),
                json.dumps(button.appearance), json.dumps(button.state_config),
                int(button.enabled), utc_now(), button.id,
            ),
        )

    def set_page(self, button_ids: list[str], page_id: str) -> None:
        with self._db.transaction() as conn:
            conn.executemany("UPDATE buttons SET page_id = ? WHERE id = ?",
                             [(page_id, bid) for bid in button_ids])

    def delete(self, button_id: str) -> bool:
        """Deletes the button; a folder's contents go with it (ON DELETE CASCADE)."""
        button = self.get(button_id)
        if button is None:
            return False
        with self._db.transaction():
            self._db.execute("DELETE FROM buttons WHERE id = ?", (button_id,))
            self.normalize_order(button.page_id, button.parent_id)
        return True

    def next_sort_order(self, page_id: str, parent_id: str | None = None) -> int:
        row = self._db.query_one(
            "SELECT COALESCE(MAX(sort_order) + 1, 0) AS n FROM buttons WHERE page_id = ? AND parent_id IS ?",
            (page_id, parent_id),
        )
        return int(row["n"])

    def reorder(self, ordered_ids: list[str]) -> None:
        renumber(self._db, "buttons", ordered_ids)

    def normalize_order(self, page_id: str, parent_id: str | None = None) -> None:
        renumber(self._db, "buttons", [b.id for b in self.list_children(page_id, parent_id)])
