"""Folders: buttons that contain buttons, nested, moved, duplicated and deleted safely."""

from __future__ import annotations

import asyncio

import pytest

from opendeck.actions import ActionError
from opendeck.db import Database
from opendeck.services.config import ButtonInput, ConfigError, PageInput


@pytest.fixture
def cfg(services):
    return services.deck_config


@pytest.fixture
def page(services):
    return services.pages.list_all()[0]


def folder(cfg, page, name, parent=None):
    return cfg.create_button(page.id, ButtonInput(kind="folder", label=name, icon_ref="builtin:mic", parent_id=parent))


def action(cfg, page, name, parent=None):
    return cfg.create_button(page.id, ButtonInput(label=name, action_type="media_play_pause", parent_id=parent))


def labels(services, page, parent=None):
    return [b.label for b in services.buttons.list_children(page.id, parent)]


def test_folder_contains_its_own_ordered_buttons(services, cfg, page) -> None:
    audio = folder(cfg, page, "Audio")
    assert audio.kind == "folder" and audio.action_type == "" and audio.action_config == {}
    for name in ("Vol +", "Vol -", "Mute"):
        action(cfg, page, name, audio.id)
    assert labels(services, page) == ["Lock PC", "Audio"]
    assert labels(services, page, audio.id) == ["Vol +", "Vol -", "Mute"]
    ids = [b.id for b in services.buttons.list_children(page.id, audio.id)]
    cfg.reorder_buttons(page.id, list(reversed(ids)), audio.id)
    assert labels(services, page, audio.id) == ["Mute", "Vol -", "Vol +"]


def test_nested_folders_and_snapshot_fields(services, cfg, page) -> None:
    audio = folder(cfg, page, "Audio")
    advanced = folder(cfg, page, "Advanced", audio.id)
    mixer = action(cfg, page, "Mixer", advanced.id)
    snap = {b["id"]: b for b in services.snapshots.build()["buttons"]}
    assert snap[advanced.id]["parentId"] == audio.id and snap[advanced.id]["kind"] == "folder"
    assert snap[mixer.id]["parentId"] == advanced.id and snap[mixer.id]["kind"] == "action"
    assert snap[audio.id]["iconRef"] == "builtin:mic"


def test_folder_needs_a_name_and_a_real_parent(cfg, page) -> None:
    with pytest.raises(ConfigError) as exc:
        cfg.create_button(page.id, ButtonInput(kind="folder", label="  "))
    assert exc.value.fields == {"label": "Enter a name."}
    lock = action(cfg, page, "Not a folder")
    with pytest.raises(ConfigError):
        action(cfg, page, "x", parent=lock.id)


def test_pressing_a_folder_never_runs_anything(services, cfg, page) -> None:
    audio = folder(cfg, page, "Audio")
    with pytest.raises(ActionError) as exc:
        asyncio.run(services.engine.execute_button(audio.id, "dev"))
    assert exc.value.code == "NOT_AN_ACTION"


def test_move_into_and_out_of_folders(services, cfg, page) -> None:
    audio = folder(cfg, page, "Audio")
    vol = action(cfg, page, "Vol +")
    cfg.move_button(vol.id, page.id, audio.id)
    assert labels(services, page, audio.id) == ["Vol +"]
    assert labels(services, page) == ["Lock PC", "Audio"]
    cfg.move_button(vol.id, page.id, None)
    assert labels(services, page) == ["Lock PC", "Audio", "Vol +"]


def test_no_circular_folders(cfg, page) -> None:
    a = folder(cfg, page, "A")
    b = folder(cfg, page, "B", a.id)
    c = folder(cfg, page, "C", b.id)
    for target in (a.id, b.id, c.id):
        with pytest.raises(ConfigError) as exc:
            cfg.move_button(a.id, page.id, target)
        assert exc.value.code == "CIRCULAR_FOLDER"


def test_moving_a_folder_to_another_page_moves_its_contents(services, cfg, page) -> None:
    other = cfg.create_page(page.profile_id, PageInput(name="Other"))
    audio = folder(cfg, page, "Audio")
    deep = folder(cfg, page, "Deep", audio.id)
    leaf = action(cfg, page, "Leaf", deep.id)
    cfg.move_button(audio.id, other.id, None)
    assert services.buttons.get(leaf.id).page_id == other.id
    assert services.buttons.get(deep.id).parent_id == audio.id
    with pytest.raises(ConfigError) as exc:  # target folder must be on the target page
        cfg.move_button(leaf.id, page.id, deep.id)
    assert exc.value.code == "WRONG_PAGE"


def test_duplicate_folder_copies_the_whole_tree(services, cfg, page) -> None:
    audio = folder(cfg, page, "Audio")
    action(cfg, page, "Vol +", audio.id)
    adv = folder(cfg, page, "Advanced", audio.id)
    action(cfg, page, "Mixer", adv.id)
    copy = cfg.duplicate_button(audio.id)
    assert copy.label == "Audio copy" and labels(services, page) == ["Lock PC", "Audio", "Audio copy"]
    assert labels(services, page, copy.id) == ["Vol +", "Advanced"]
    adv_copy = services.buttons.list_children(page.id, copy.id)[1]
    assert adv_copy.id != adv.id and labels(services, page, adv_copy.id) == ["Mixer"]
    cfg.delete_button(adv_copy.id)  # copies are independent
    assert labels(services, page, adv.id) == ["Mixer"]


def test_delete_folder_removes_everything_inside(services, cfg, page) -> None:
    audio = folder(cfg, page, "Audio")
    adv = folder(cfg, page, "Advanced", audio.id)
    leaf = action(cfg, page, "Leaf", adv.id)
    cfg.delete_button(audio.id)
    assert services.buttons.get(leaf.id) is None and services.buttons.get(adv.id) is None
    assert labels(services, page) == ["Lock PC"]


def test_page_duplication_keeps_folders(services, cfg, page) -> None:
    audio = folder(cfg, page, "Audio")
    action(cfg, page, "Vol +", audio.id)
    copy = cfg.duplicate_page(page.id)
    copied_folder = next(b for b in services.buttons.list_for_page(copy.id) if b.kind == "folder")
    assert labels(services, copy, copied_folder.id) == ["Vol +"]


def test_folder_cannot_become_action_while_not_empty(cfg, page) -> None:
    audio = folder(cfg, page, "Audio")
    action(cfg, page, "Vol +", audio.id)
    with pytest.raises(ConfigError) as exc:
        cfg.update_button(audio.id, ButtonInput(label="Audio", action_type="media_play_pause"))
    assert exc.value.code == "FOLDER_NOT_EMPTY"


def test_existing_buttons_survive_folder_migration(tmp_path) -> None:
    path = tmp_path / "v3.sqlite3"
    db = Database(path)
    db.migrate(up_to=3)
    db.execute("INSERT INTO profiles(id, name, sort_order, created_at) VALUES ('pr', 'P', 0, 't')")
    db.execute("INSERT INTO pages(id, profile_id, name, created_at) VALUES ('pg', 'pr', 'Main', 't')")
    db.execute("INSERT INTO buttons(id, page_id, sort_order, label, action_type, created_at, updated_at)"
               " VALUES ('b', 'pg', 0, 'Chrome', 'launch_application', 't', 't')")
    db.close()
    upgraded = Database(path)
    assert upgraded.migrate() == [4, 5]
    row = upgraded.query_one("SELECT label, kind, parent_id FROM buttons")
    assert (row["label"], row["kind"], row["parent_id"]) == ("Chrome", "action", None)
    upgraded.close()


def test_folder_api(client, services, page) -> None:
    f = client.post(f"/api/admin/pages/{page.id}/buttons", json={"kind": "folder", "label": "System"}).json()
    child = client.post(f"/api/admin/pages/{page.id}/buttons", json={
        "label": "Sleep", "actionType": "sleep", "parentId": f["id"]}).json()
    assert child["parentId"] == f["id"]
    lock = services.buttons.list_for_page(page.id)[0]
    moved = client.post(f"/api/admin/buttons/{lock.id}/move", json={"pageId": page.id, "parentId": f["id"]})
    assert moved.status_code == 200
    order = client.put(f"/api/admin/pages/{page.id}/buttons-order",
                       json={"ids": [lock.id, child["id"]], "parentId": f["id"]})
    assert order.status_code == 204
    assert [b.label for b in services.buttons.list_children(page.id, f["id"])] == ["Lock PC", "Sleep"]
    circular = client.post(f"/api/admin/buttons/{f['id']}/move", json={"pageId": page.id, "parentId": f["id"]})
    assert circular.status_code == 409
