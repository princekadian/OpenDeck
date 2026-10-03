from __future__ import annotations

from fastapi.testclient import TestClient

from opendeck.server.http import create_app
from opendeck.server.network import is_lan


def test_info_is_public(client) -> None:
    body = client.get("/api/info").json()
    assert body["protocolVersion"] == 2


def test_pair_with_wrong_code(client, services) -> None:
    code, _ = services.pairing.current_code()
    wrong = "000000" if code != "000000" else "111111"
    response = client.post("/api/pair", json={"code": wrong, "deviceName": "x"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_code"


def test_pair_rejects_malformed_code(client) -> None:
    assert client.post("/api/pair", json={"code": "12ab56"}).status_code == 422


def test_admin_status_available_on_loopback(client) -> None:
    body = client.get("/api/admin/status").json()
    assert len(body["pairing"]["code"]) == 6


def test_admin_blocked_for_lan_clients(services) -> None:
    lan_client = TestClient(create_app(services), client=("192.168.1.50", 5000))
    assert lan_client.get("/api/info").status_code == 200
    assert lan_client.get("/api/admin/status").status_code == 403


def test_public_internet_clients_blocked(services) -> None:
    wan_client = TestClient(create_app(services), client=("8.8.8.8", 5000))
    assert wan_client.get("/api/info").status_code == 403


def test_is_lan_classification() -> None:
    assert is_lan("127.0.0.1") and is_lan("192.168.0.4") and is_lan("10.1.2.3")
    assert is_lan("fe80::1") and is_lan("::ffff:192.168.1.2")
    assert not is_lan("8.8.8.8") and not is_lan(None)


def test_revoke_disconnects_device(client, services, paired_token) -> None:
    device_id = services.devices.list()[0].id
    assert client.post(f"/api/admin/devices/{device_id}/revoke").status_code == 200
    assert services.pairing.authenticate(paired_token) is None


def test_serves_dashboard_and_spa_routes(services, tmp_path) -> None:
    import dataclasses

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>deck</html>")
    (dist / "assets" / "app-1234.js").write_text("console.log(1)")
    services.config = dataclasses.replace(services.config, static_dir=dist)
    client = TestClient(create_app(services))
    assert client.get("/").text == "<html>deck</html>"
    assert client.get("/editor").text == "<html>deck</html>"
    asset = client.get("/assets/app-1234.js")
    assert "immutable" in asset.headers["cache-control"]
    assert client.get("/../secret").status_code in (200, 404)  # falls back to index, never escapes
    (dist / "index.html").unlink()  # mid-rebuild
    assert client.get("/").status_code == 503
