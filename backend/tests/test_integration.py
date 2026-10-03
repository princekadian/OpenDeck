"""End-to-end over real TCP: HTTP pairing, WebSocket handshake, action round trip.

Uses the recording lock action, so the developer's PC is never locked.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.request

import pytest
import uvicorn
from websockets.asyncio.client import connect

from opendeck.server.http import create_app


@pytest.fixture
def live_server(services):
    server = uvicorn.Server(uvicorn.Config(create_app(services), host="127.0.0.1", port=0,
                                          log_config=None, ws_max_size=64 * 1024))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _post_json(url: str, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def test_ipad_to_windows_round_trip(live_server, services, lock_action) -> None:
    code, _ = services.pairing.current_code()
    token = _post_json(f"http://{live_server}/api/pair", {"code": code, "deviceName": "iPad"})["token"]

    async def scenario() -> list[dict]:
        async with connect(f"ws://{live_server}/ws") as ws:
            await ws.send(json.dumps({"version": 2, "type": "HELLO", "payload": {"token": token}}))
            welcome = json.loads(await ws.recv())
            snapshot = json.loads(await ws.recv())
            button_id = snapshot["payload"]["buttons"][0]["id"]
            started = time.perf_counter()
            await ws.send(json.dumps({"version": 2, "type": "ACTION_EXECUTE", "requestId": "e2e",
                                      "payload": {"buttonId": button_id}}))
            result = json.loads(await asyncio.wait_for(ws.recv(), 5))
            result["_latency_ms"] = (time.perf_counter() - started) * 1000
            return [welcome, snapshot, result]

    welcome, snapshot, result = asyncio.run(scenario())
    assert welcome["type"] == "WELCOME"
    assert snapshot["type"] == "SNAPSHOT"
    assert result["type"] == "ACTION_RESULT" and result["success"] is True
    assert result["requestId"] == "e2e"
    assert result["_latency_ms"] < 250
    assert len(lock_action.calls) == 1


def test_two_devices_see_each_other(live_server, services) -> None:
    tokens = []
    for name in ("iPad A", "iPad B"):
        code, _ = services.pairing.current_code()
        tokens.append(_post_json(f"http://{live_server}/api/pair",
                                 {"code": code, "deviceName": name})["token"])

    async def scenario() -> dict:
        async with connect(f"ws://{live_server}/ws") as a:
            await a.send(json.dumps({"version": 2, "type": "HELLO", "payload": {"token": tokens[0]}}))
            await a.recv(), await a.recv()
            async with connect(f"ws://{live_server}/ws") as b:
                await b.send(json.dumps({"version": 2, "type": "HELLO",
                                         "payload": {"token": tokens[1]}}))
                return json.loads(await asyncio.wait_for(a.recv(), 5))

    notice = asyncio.run(scenario())
    assert notice["type"] == "DEVICE_CONNECTED"
    assert notice["payload"]["deviceName"] == "iPad B"
