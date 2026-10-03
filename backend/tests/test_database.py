from __future__ import annotations

from pathlib import Path

from opendeck.db import Database


def test_migrations_apply_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.sqlite3")
    assert db.migrate() == [1, 2, 3, 4, 5]
    assert db.migrate() == []
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "profiles", "pages", "buttons", "devices"} <= tables
    db.close()


def test_data_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "x.sqlite3"
    db = Database(path)
    db.migrate()
    db.execute("INSERT INTO settings(key, value) VALUES ('a', 'b')")
    db.close()

    reopened = Database(path)
    assert reopened.migrate() == []
    assert reopened.query_one("SELECT value FROM settings WHERE key='a'")["value"] == "b"
    reopened.close()


def test_seed_creates_lock_button(services) -> None:
    profile_id = services.deck_config.active_profile_id()
    buttons = services.buttons.list_for_profile(profile_id)
    assert [b.action_type for b in buttons] == ["lock_windows"]
    assert [p.name for p in services.pages.list_pages(profile_id)] == ["Home", "System Monitoring"]


def test_v1_database_upgrades_without_losing_configuration(tmp_path: Path) -> None:
    """A Milestone 1 database (grid positions) keeps its buttons, in row-major order."""
    path = tmp_path / "old.sqlite3"
    db = Database(path)
    db.migrate(up_to=1)
    db.execute("INSERT INTO profiles VALUES ('pr', 'Default', 0, 't')")
    db.execute("INSERT INTO pages(id, profile_id, name, sort_order, rows, cols, created_at)"
               " VALUES ('pg', 'pr', 'Main', 0, 3, 5, 't')")
    for bid, row, col in (("c", 2, 0), ("a", 0, 3), ("b", 1, 1)):
        db.execute("INSERT INTO buttons(id, page_id, row, col, label, action_type, created_at,"
                   " updated_at) VALUES (?, 'pg', ?, ?, ?, 'lock_windows', 't', 't')",
                   (bid, row, col, bid.upper()))
    db.close()

    upgraded = Database(path)
    assert upgraded.migrate() == [2, 3, 4, 5]
    rows = upgraded.query("SELECT id, sort_order, label, enabled FROM buttons ORDER BY sort_order")
    assert [(r["id"], r["sort_order"], r["label"], r["enabled"]) for r in rows] == [
        ("a", 0, "A", 1), ("b", 1, "B", 1), ("c", 2, "C", 1)]
    assert upgraded.query_one("SELECT description FROM profiles")["description"] == ""
    assert list(tmp_path.glob("old.v0001.bak")), "backup taken before migrating"
    upgraded.close()
