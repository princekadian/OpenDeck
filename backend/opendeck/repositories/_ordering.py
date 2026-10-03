"""Shared helper for sibling ordering (profiles, pages within a profile, buttons within a page)."""

from __future__ import annotations

from ..db import Database

# Table names are fixed by callers, never user input.
_ORDERED_TABLES = frozenset({"profiles", "pages", "buttons"})


def renumber(db: Database, table: str, ordered_ids: list[str]) -> None:
    """Write sort_order = 0..n-1 following `ordered_ids`."""
    if table not in _ORDERED_TABLES:
        raise ValueError(table)
    with db.transaction() as conn:
        conn.executemany(
            f"UPDATE {table} SET sort_order = ? WHERE id = ?",
            [(index, item_id) for index, item_id in enumerate(ordered_ids)],
        )
