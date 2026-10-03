"""Behaviour of the new actions with Windows calls replaced by recorders."""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from opendeck.actions import ActionError
from opendeck.native.windows import keyboard, power, winmgmt
from opendeck.services.audio import AudioLevel
from opendeck.services.config import ButtonInput, ConfigError

from .conftest import hello


class FakeAudio:
    def __init__(self) -> None:
        self.levels = {"output": AudioLevel(40, False), "input": AudioLevel(80, False)}
        self.default = {"output": "spk-1", "input": "mic-1"}

    async def level(self, flow, device_id=None):
        return self.levels[flow]

    async def set_volume(self, flow, percent, device_id=None):
        self.levels[flow] = AudioLevel(max(0, min(100, percent)), False)
        return self.levels[flow]

    async def change_volume(self, flow, delta, device_id=None):
        return await self.set_volume(flow, self.levels[flow].volume + delta)

    async def set_mute(self, flow, muted, device_id=None):
        current = self.levels[flow]
        self.levels[flow] = AudioLevel(current.volume, (not current.muted) if muted is None else muted)
        return self.levels[flow]

    async def devices(self, flow):
        ids = ["spk-1", "spk-2"] if flow == "output" else ["mic-1", "mic-2"]
        return [{"id": i, "name": i.upper(), "isDefault": i == self.default[flow]} for i in ids]

    async def set_default(self, device_id):
        self.default["output" if device_id.startswith("spk") else "input"] = device_id

    def close(self):
        pass


@pytest.fixture
def audio(services):
    fake = FakeAudio()
    services.engine.runtime.services["audio"] = fake
    return fake


@pytest.fixture
def page_id(services):
    return services.pages.list_all()[0].id


def add(services, page_id, action_type, config=None, label="Key"):
    return services.deck_config.create_button(
        page_id, ButtonInput(label=label, action_type=action_type, action_config=config or {}))


def press(services, button, **kw):
    return asyncio.run(services.engine.execute_button(button.id, "dev", **kw))


async def _press_and_refresh(services, button, **kw):
    outcome = await services.engine.execute_button(button.id, "dev", **kw)
    return outcome


# ---- system --------------------------------------------------------------------------


def test_shutdown_requires_second_tap_by_default(services, page_id, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(power, "shutdown", lambda: calls.append("shutdown"))
    button = add(services, page_id, "shutdown")
    with pytest.raises(ActionError) as exc:
        press(services, button)
    assert exc.value.code == "CONFIRMATION_REQUIRED" and calls == []
    press(services, button, confirmed=True)
    assert calls == ["shutdown"]
    snapshot_button = next(b for b in services.snapshots.build()["buttons"] if b["id"] == button.id)
    assert snapshot_button["confirm"] is True and snapshot_button["iconRef"] == "builtin:power"


def test_confirmation_can_be_turned_off(services, page_id, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(power, "restart", lambda: calls.append("restart"))
    press(services, add(services, page_id, "restart", {"confirm": False}))
    assert calls == ["restart"]


def test_hibernate_unavailable_is_reported(services, page_id, monkeypatch) -> None:
    monkeypatch.setattr(power, "hibernate_available", lambda: False)
    with pytest.raises(ActionError) as exc:
        press(services, add(services, page_id, "hibernate", {"confirm": False}))
    assert exc.value.code == "HIBERNATE_UNAVAILABLE"


def test_settings_page_choice_is_validated(services, page_id) -> None:
    with pytest.raises(ConfigError):
        add(services, page_id, "open_settings", {"page": "registry-editor"})
    assert add(services, page_id, "open_settings", {"page": "sound"}).action_config == {"page": "sound"}


# ---- audio + state -------------------------------------------------------------------


def test_volume_actions_change_level_and_publish_state(services, page_id, audio) -> None:
    up = add(services, page_id, "volume_up", {"amount": 10})
    mute = add(services, page_id, "mute_toggle")
    assert press(services, up).data == {"volume": 50, "muted": False}
    assert services.states.get(up.id).detail["text"] == "50%"
    press(services, mute)
    state = services.states.get(mute.id)
    assert state.state == "muted" and state.detail["icon"] == "volume-off"
    # Both keys show the same device: the volume key also shows Muted now.
    asyncio.run(services.state_coordinator.refresh())
    assert services.states.get(up.id).detail["text"] == "Muted"


def test_set_volume_bounds_validated(services, page_id) -> None:
    with pytest.raises(ConfigError) as exc:
        add(services, page_id, "set_volume", {"volume": 150})
    assert "volume" in exc.value.fields


def test_mic_mute_state_labels(services, page_id, audio) -> None:
    mic = add(services, page_id, "mic_mute")
    press(services, mic)
    assert services.states.get(mic.id).detail["text"] == "Mic muted"
    press(services, mic)
    assert services.states.get(mic.id).detail["text"] == "Mic on"


def test_change_output_device(services, page_id, audio) -> None:
    switch = add(services, page_id, "audio_output_device", {"deviceId": "spk-2"})
    press(services, switch)
    assert audio.default["output"] == "spk-2"
    assert services.states.get(switch.id).state == "active"
    gone = add(services, page_id, "audio_output_device", {"deviceId": "spk-9"})
    with pytest.raises(ActionError) as exc:
        press(services, gone)
    assert exc.value.code == "DEVICE_NOT_FOUND"


# ---- keyboard ------------------------------------------------------------------------


@pytest.fixture
def keys(monkeypatch):
    sent = []
    monkeypatch.setattr(keyboard, "press_combo", lambda mods, key: sent.append(("combo", tuple(mods), key)))
    monkeypatch.setattr(keyboard, "type_text", lambda text: sent.append(("text", text)))
    return sent


def test_hotkey_is_stored_structurally_and_normalised(services, page_id, keys) -> None:
    button = add(services, page_id, "hotkey", {"shortcut": {"modifiers": ["SHIFT", "CTRL", "CTRL"], "key": "s"}})
    assert button.action_config == {"shortcut": {"modifiers": ["CTRL", "SHIFT"], "key": "S"}}
    assert press(services, button).message == "Ctrl + Shift + S"
    assert keys == [("combo", ("CTRL", "SHIFT"), "S")]


def test_unknown_key_rejected(services, page_id) -> None:
    with pytest.raises(ConfigError) as exc:
        add(services, page_id, "key_press", {"key": "HYPER"})
    assert "key" in exc.value.fields


def test_type_text_and_media_keys(services, page_id, keys) -> None:
    press(services, add(services, page_id, "type_text", {"text": "héllo ✓"}))
    press(services, add(services, page_id, "media_play_pause"))
    assert keys == [("text", "héllo ✓"), ("combo", (), "MEDIA_PLAY_PAUSE")]


# ---- windows / applications -------------------------------------------------------------


def test_active_window_actions(services, page_id, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(winmgmt, "foreground_window", lambda: 42)
    monkeypatch.setattr(winmgmt, "show", lambda hwnd, cmd: calls.append(("show", hwnd, cmd)))
    monkeypatch.setattr(winmgmt, "move_window", lambda hwnd, x, y: calls.append(("move", hwnd, x, y)))
    press(services, add(services, page_id, "window_minimize"))
    press(services, add(services, page_id, "window_move", {"x": 10, "y": 20}))
    assert calls == [("show", 42, winmgmt.SW_MINIMIZE), ("move", 42, 10, 20)]


def test_app_running_state(services, page_id, monkeypatch) -> None:
    running = {"pids": [7]}
    monkeypatch.setattr(winmgmt, "find_processes", lambda path: running["pids"])
    button = add(services, page_id, "app_running", {"path": "C:\\Apps\\Chrome.exe"})
    assert press(services, button).data == {"running": True}
    assert services.states.get(button.id).detail["text"] == "Running"
    running["pids"] = []
    asyncio.run(services.state_coordinator.refresh(polled_only=True))
    assert services.states.get(button.id).detail["text"] == "Not running"


def test_close_app_not_running(services, page_id, monkeypatch) -> None:
    monkeypatch.setattr(winmgmt, "find_processes", lambda path: [])
    with pytest.raises(ActionError) as exc:
        press(services, add(services, page_id, "app_close", {"path": "C:\\Apps\\X.exe"}))
    assert exc.value.code == "APP_NOT_RUNNING"


# ---- navigation --------------------------------------------------------------------------


def test_go_to_page_navigates_only_the_pressing_device(client, services, paired_token, page_id) -> None:
    target = services.deck_config.create_page(services.profiles.list()[0].id,
                                              __import__("opendeck.services.config", fromlist=["PageInput"]).PageInput(name="Games"))
    button = add(services, page_id, "go_to_page", {"pageId": target.id})
    with client.websocket_connect("/ws") as ws:
        ws.send_json(hello(paired_token))
        ws.receive_json(), ws.receive_json()
        ws.send_json({"version": 2, "type": "ACTION_EXECUTE", "requestId": "n", "payload": {"buttonId": button.id}})
        first, second = ws.receive_json(), ws.receive_json()
        by_type = {m["type"]: m for m in (first, second)}
        assert by_type["NAVIGATE"]["payload"] == {"pageId": target.id}
        assert by_type["ACTION_RESULT"]["success"] is True


def test_navigation_from_editor_test_explains_itself(services) -> None:
    with pytest.raises(ActionError) as exc:
        asyncio.run(services.engine.execute_draft("go_back", {}))
    assert exc.value.code == "DEVICE_ONLY"


# ---- workflow ----------------------------------------------------------------------------


def test_multi_action_runs_steps_in_order(services, page_id, keys, audio) -> None:
    button = add(services, page_id, "multi_action", {"steps": [
        {"actionType": "set_volume", "actionConfig": {"volume": 30}},
        {"actionType": "delay", "actionConfig": {"milliseconds": 10}},
        {"actionType": "hotkey", "actionConfig": {"shortcut": {"modifiers": ["CTRL"], "key": "G"}}},
    ]})
    assert press(services, button).message == "3 actions done"
    assert audio.levels["output"].volume == 30
    assert keys == [("combo", ("CTRL",), "G")]


def test_multi_action_validates_each_step(services, page_id) -> None:
    with pytest.raises(ConfigError) as exc:
        add(services, page_id, "multi_action", {"steps": [
            {"actionType": "delay", "actionConfig": {}},
            {"actionType": "open_url", "actionConfig": {"url": "javascript:alert(1)"}},
        ]})
    assert "Step 2 (Open website)" in exc.value.fields["steps"]
    with pytest.raises(ConfigError) as exc:
        add(services, page_id, "multi_action", {"steps": [{"actionType": "multi_action", "actionConfig": {}}]})
    assert "can't be nested" in exc.value.fields["steps"]


def test_multi_action_stops_on_first_error(services, page_id, keys, tmp_path) -> None:
    button = add(services, page_id, "multi_action", {"steps": [
        {"actionType": "open_folder", "actionConfig": {"path": str(tmp_path / "missing")}},
        {"actionType": "type_text", "actionConfig": {"text": "never"}},
    ]})
    with pytest.raises(ActionError) as exc:
        press(services, button)
    assert exc.value.message.startswith("Step 1 (Open folder):")
    assert keys == []


def test_toggle_alternates_and_remembers_state_across_restart(services, page_id, keys, tmp_path) -> None:
    button = add(services, page_id, "toggle", {
        "onAction": {"actionType": "type_text", "actionConfig": {"text": "A"}},
        "offAction": {"actionType": "type_text", "actionConfig": {"text": "B"}},
        "onLabel": "Live", "offLabel": "Idle",
    })
    press(services, button)
    assert services.states.get(button.id).detail["text"] == "Live"
    press(services, button)
    press(services, button)
    assert keys == [("text", "A"), ("text", "B"), ("text", "A")]
    assert services.runtime_store.get(f"toggle:{button.id}") == {"on": True}


def test_counters_share_values_by_name(services, page_id) -> None:
    plus = add(services, page_id, "counter", {"name": "Kills", "operation": "increment", "amount": 2})
    minus = add(services, page_id, "counter", {"name": "kills", "operation": "decrement"})
    reset = add(services, page_id, "counter", {"name": "Kills", "operation": "reset", "initialValue": 10})
    press(services, plus)
    press(services, plus)
    press(services, minus)
    assert services.states.get(plus.id).detail["text"] == "3"
    assert services.states.get(minus.id).detail["text"] == "3"
    press(services, reset)
    assert services.states.get(plus.id).detail["text"] == "10"


def test_timer_start_pause_reset(services, page_id) -> None:
    start = add(services, page_id, "timer", {"name": "Break", "minutes": 1})
    reset = add(services, page_id, "timer", {"name": "Break", "minutes": 1, "operation": "reset"})

    async def scenario():
        await services.engine.execute_button(start.id, "dev")
        running = services.states.get(start.id)
        await services.engine.execute_button(start.id, "dev")
        paused = services.states.get(start.id)
        await services.engine.execute_button(reset.id, "dev")
        return running, paused, services.states.get(start.id)

    running, paused, after_reset = asyncio.run(scenario())
    assert running.state.startswith("running:") and running.detail["countdown"]["running"] is True
    assert paused.state == "paused" and 59_000 < paused.detail["countdown"]["remainingMs"] <= 60_000
    assert after_reset.state == "idle" and after_reset.detail["countdown"]["remainingMs"] == 60_000


# ---- advanced -----------------------------------------------------------------------------


def test_run_command_and_powershell_really_run(services, page_id) -> None:
    ok = add(services, page_id, "run_command", {"command": "echo hello"})
    assert "hello" in press(services, ok).data["output"]
    failing = add(services, page_id, "run_command", {"command": "exit 3"})
    with pytest.raises(ActionError) as exc:
        press(services, failing)
    assert exc.value.code == "EXIT_CODE" and "3" in exc.value.message
    ps = add(services, page_id, "run_powershell", {"script": "$x = 'ünïcode'; Write-Output \"[$x]\""})
    assert "[ünïcode]" in press(services, ps).data["output"]


def test_device_cannot_inject_commands(client, services, paired_token, page_id) -> None:
    """The WebSocket payload has no field that could carry a command; extra fields are ignored."""
    button = add(services, page_id, "run_command", {"command": "echo safe"})
    with client.websocket_connect("/ws") as ws:
        ws.send_json(hello(paired_token))
        ws.receive_json(), ws.receive_json()
        ws.send_json({"version": 2, "type": "ACTION_EXECUTE", "requestId": "x",
                      "payload": {"buttonId": button.id, "command": "del C:\\", "actionConfig": {"command": "x"}}})
        result = ws.receive_json()
        assert result["success"] is True and "safe" in result["payload"]["data"]["output"]


@pytest.fixture
def http_server():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.headers.get("X-Token"), self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(201)
            self.end_headers()

        def do_GET(self):
            self.send_response(500)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def test_http_request(services, page_id, http_server) -> None:
    base, received = http_server
    ok = add(services, page_id, "http_request", {"method": "POST", "url": base + "/hook",
                                                  "headers": "X-Token: abc", "body": '{"a":1}'})
    assert press(services, ok).data == {"status": 201}
    assert received == [("/hook", "abc", b'{"a":1}')]
    failing = add(services, page_id, "http_request", {"url": base + "/err"})
    with pytest.raises(ActionError) as exc:
        press(services, failing)
    assert exc.value.code == "HTTP_ERROR"
    with pytest.raises(ConfigError):
        add(services, page_id, "http_request", {"url": "file:///C:/Windows/win.ini"})
    with pytest.raises(ConfigError):
        add(services, page_id, "http_request", {"url": base, "headers": "not a header"})


def test_websocket_action(services, page_id) -> None:
    from websockets.asyncio.server import serve

    async def scenario():
        async def echo(ws):
            async for msg in ws:
                await ws.send("got " + msg)

        async with serve(echo, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            button = add(services, page_id, "websocket_message",
                         {"url": f"ws://127.0.0.1:{port}", "message": "hi", "waitForReply": True})
            return await services.engine.execute_button(button.id, "dev")

    assert asyncio.run(scenario()).data == {"reply": "got hi"}
