from __future__ import annotations

import time

from fastapi.testclient import TestClient

from opendeck.imaging import encode_png_rgba
from opendeck.server.http import create_app

from .conftest import hello


def _tree(client) -> dict:
    return client.get("/api/admin/config").json()


def test_config_tree_includes_actions_and_full_button_config(client) -> None:
    tree = _tree(client)
    assert {a["type"] for a in tree["actions"]} >= {
        "launch_application", "open_url", "open_file", "open_folder", "lock_windows"}
    assert tree["buttons"][0]["actionConfig"] == {}
    assert tree["activeProfileId"] == tree["profiles"][0]["id"]


def test_admin_api_is_pc_only(services) -> None:
    lan = TestClient(create_app(services), client=("192.168.1.20", 5000))
    assert lan.get("/api/admin/config").status_code == 403
    assert lan.post("/api/admin/profiles", json={"name": "x"}).status_code == 403
    assert lan.post("/api/admin/actions/test", json={"actionType": "lock_windows"}).status_code == 403


def test_button_crud_via_api(client) -> None:
    page_id = _tree(client)["pages"][0]["id"]
    created = client.post(f"/api/admin/pages/{page_id}/buttons", json={
        "label": "YouTube", "iconRef": "builtin:globe", "actionType": "open_url",
        "actionConfig": {"url": "youtube.com"}})
    assert created.status_code == 201
    button = created.json()
    assert button["actionConfig"] == {"url": "https://youtube.com"}

    bad = client.patch(f"/api/admin/buttons/{button['id']}", json={
        "label": "YouTube", "actionType": "open_url", "actionConfig": {"url": "ftp://x"}})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "INVALID_CONFIG"
    assert "url" in bad.json()["detail"]["fields"]

    assert client.put(f"/api/admin/buttons/{button['id']}/enabled",
                      json={"enabled": False}).json()["enabled"] is False
    ids = [b["id"] for b in _tree(client)["buttons"]]
    assert client.put(f"/api/admin/pages/{page_id}/buttons-order",
                      json={"ids": list(reversed(ids))}).status_code == 204
    assert [b["label"] for b in _tree(client)["buttons"]] == ["YouTube", "Lock PC"]
    assert client.delete(f"/api/admin/buttons/{button['id']}").status_code == 204
    assert client.delete(f"/api/admin/buttons/{button['id']}").status_code == 404


def test_profile_and_page_endpoints(client) -> None:
    profile = client.post("/api/admin/profiles", json={"name": "Gaming"}).json()
    page = client.post(f"/api/admin/profiles/{profile['id']}/pages", json={"name": "Discord"}).json()
    client.patch(f"/api/admin/pages/{page['id']}", json={"name": "Voice"})
    client.post(f"/api/admin/pages/{page['id']}/duplicate")
    assert client.put("/api/admin/active-profile", json={"profileId": profile["id"]}).status_code == 204
    tree = _tree(client)
    assert tree["activeProfileId"] == profile["id"]
    assert [p["name"] for p in tree["pages"] if p["profileId"] == profile["id"]] == [
        "Main", "Voice", "Voice copy"]
    empty_name = client.post("/api/admin/profiles", json={"name": "   "})
    assert empty_name.status_code == 422


def test_icon_upload_validation_and_serving(client, services) -> None:
    png = encode_png_rgba(2, 2, bytes([255, 0, 0, 255] * 4))
    ref = client.post("/api/admin/icons", content=png,
                      headers={"content-type": "image/png"}).json()["iconRef"]
    assert ref.startswith("asset:")
    served = client.get("/api/assets/" + ref.removeprefix("asset:"))
    assert served.status_code == 200 and served.content == png
    assert "immutable" in served.headers["cache-control"]
    assert client.post("/api/admin/icons", content=b"<svg/>",
                       headers={"content-type": "image/svg+xml"}).status_code == 415
    assert client.post("/api/admin/icons", content=b"not a png",
                       headers={"content-type": "image/png"}).status_code == 400
    assert client.get("/api/assets/..%2Fdata.sqlite3").status_code == 404


def test_draft_action_test_endpoint(client, lock_action) -> None:
    result = client.post("/api/admin/actions/test", json={"actionType": "lock_windows"}).json()
    assert result == {"success": True, "message": "Windows locked"}
    missing = client.post("/api/admin/actions/test", json={
        "actionType": "open_folder", "actionConfig": {"path": "C:\\definitely\\missing"}}).json()
    assert missing["success"] is False and missing["error"]["code"] == "FOLDER_NOT_FOUND"


def test_edits_are_pushed_live_to_connected_devices(client, paired_token) -> None:
    """Editor change -> database -> WebSocket SNAPSHOT, without the device reconnecting."""
    page_id = _tree(client)["pages"][0]["id"]
    with client.websocket_connect("/ws") as ws:
        ws.send_json(hello(paired_token))
        ws.receive_json(), ws.receive_json()  # WELCOME, SNAPSHOT
        client.post(f"/api/admin/pages/{page_id}/buttons", json={
            "label": "Docs", "actionType": "open_folder", "actionConfig": {"path": "C:\\Users"}})
        client.post(f"/api/admin/pages/{page_id}/buttons", json={
            "label": "Mail", "actionType": "open_url", "actionConfig": {"url": "mail.example.com"}})
        update = ws.receive_json()
        assert update["type"] == "SNAPSHOT"
        labels = [b["label"] for b in update["payload"]["buttons"]]
        assert labels == ["Lock PC", "Docs", "Mail"]  # both edits coalesced into one update
        assert all("actionConfig" not in b for b in update["payload"]["buttons"])


def test_pick_endpoint_is_serialised(client, monkeypatch) -> None:
    from opendeck.native.windows import dialogs

    monkeypatch.setattr(dialogs, "pick_path", lambda kind: (time.sleep(0.01), "C:\\x.exe")[1])
    assert client.post("/api/admin/pick", json={"kind": "exe"}).json() == {"path": "C:\\x.exe"}
    assert client.post("/api/admin/pick", json={"kind": "bad"}).status_code == 422
