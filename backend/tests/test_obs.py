"""OBS integration against a protocol-faithful fake obs-websocket v5 server."""

from __future__ import annotations

import asyncio

import pytest

from opendeck.actions import ActionError
from opendeck.integrations.obs import ObsSettings, ObsStatus, auth_response
from opendeck.services.config import ButtonInput

from .fake_obs import FakeObs


def test_auth_matches_protocol_example() -> None:
    # Example from the obs-websocket protocol documentation.
    assert auth_response("supersecretpassword", "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=",
                         "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY=") == "1Ct943GAT+6YQUUX47Ia/ncufilbe6+oD6lY+5kaCu4="


async def wait_for(predicate, timeout=5.0):
    end = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def run(services, scenario):
    """Run a scenario with the OBS integration running on the test's event loop."""

    async def main():
        try:
            await scenario(services)
        finally:
            await services.obs.stop()

    asyncio.run(main())


def add(services, action_type, config=None, label="Key"):
    page = services.pages.list_all()[0]
    return services.deck_config.create_button(page.id, ButtonInput(label=label, action_type=action_type,
                                                                   action_config=config or {}))


async def connect(services, fake, password="secret"):
    services.obs.configure(ObsSettings(enabled=True, host="127.0.0.1", port=fake.port, password=password))
    await wait_for(lambda: services.obs.status in (ObsStatus.CONNECTED, ObsStatus.AUTH_FAILED))


def text(services, button):
    state = services.states.get(button.id)
    return state.detail.get("text") if state else None


def test_connects_authenticates_and_syncs_state(services) -> None:
    async def scenario(svc):
        fake = await FakeObs().start()
        try:
            await connect(svc, fake)
            assert svc.obs.status == ObsStatus.CONNECTED
            assert svc.obs.obs_version == "32.1.2"
            assert svc.obs.state.program_scene == "Gameplay"
            assert await svc.obs.scenes() == ["Starting", "Gameplay", "BRB"]
            assert await svc.obs.inputs("audio") == ["Mic/Aux", "Desktop Audio"]
            assert await svc.obs.inputs("video") == ["Webcam"]
            assert await svc.obs.scene_sources("") == ["Webcam", "Overlay"]
        finally:
            await fake.stop()

    run(services, scenario)


def test_wrong_password_stops_retrying(services) -> None:
    async def scenario(svc):
        fake = await FakeObs().start()
        try:
            await connect(svc, fake, password="nope")
            assert svc.obs.status == ObsStatus.AUTH_FAILED
            await asyncio.sleep(1.5)
            assert fake.requests == []  # no reconnect storm, no requests
        finally:
            await fake.stop()

    run(services, scenario)


def test_reconnects_when_obs_starts_later_and_after_restart(services) -> None:
    async def scenario(svc):
        fake = FakeObs()
        fake.port = 47555
        svc.obs.configure(ObsSettings(enabled=True, host="127.0.0.1", port=fake.port, password="secret"))
        await wait_for(lambda: svc.obs.status == ObsStatus.UNREACHABLE)
        await fake.start()
        await wait_for(lambda: svc.obs.connected, timeout=8)
        await fake.stop()
        await wait_for(lambda: not svc.obs.connected)
        await fake.start()
        await wait_for(lambda: svc.obs.connected, timeout=8)
        await fake.stop()

    run(services, scenario)


def test_streaming_actions_and_live_key_state(services) -> None:
    start = add(services, "obs_start_streaming", label="Go live")
    stop = add(services, "obs_stop_streaming", label="End")

    async def scenario(svc):
        fake = await FakeObs().start()
        try:
            await connect(svc, fake)
            await svc.state_coordinator.refresh()
            assert text(svc, start) == "Not live"
            await svc.engine.execute_button(start.id, "dev")
            await wait_for(lambda: text(svc, start) == "Live" and text(svc, stop) == "Live")
            with pytest.raises(ActionError) as exc:
                await svc.engine.execute_button(start.id, "dev")
            assert exc.value.code == "OBS_ALREADY_ACTIVE"
            await svc.engine.execute_button(stop.id, "dev")
            await wait_for(lambda: text(svc, start) == "Not live")
        finally:
            await fake.stop()

    run(services, scenario)


def test_recording_pause_resume(services) -> None:
    rec = add(services, "obs_start_recording")
    pause = add(services, "obs_pause_recording")
    stop = add(services, "obs_stop_recording")

    async def scenario(svc):
        fake = await FakeObs().start()
        try:
            await connect(svc, fake)
            with pytest.raises(ActionError) as exc:
                await svc.engine.execute_button(pause.id, "dev")
            assert exc.value.code == "OBS_NOT_ACTIVE"
            await svc.engine.execute_button(rec.id, "dev")
            await wait_for(lambda: text(svc, rec) == "REC")
            await svc.engine.execute_button(pause.id, "dev")
            await wait_for(lambda: text(svc, pause) == "Paused")
            await svc.engine.execute_button(pause.id, "dev")
            await wait_for(lambda: text(svc, pause) == "REC")
            outcome = await svc.engine.execute_button(stop.id, "dev")
            assert outcome.data == {"path": "C:\\Videos\\rec.mkv"}
            await wait_for(lambda: text(svc, rec) == "Not recording")
        finally:
            await fake.stop()

    run(services, scenario)


def test_scene_keys_follow_obs_including_changes_made_in_obs(services) -> None:
    brb = add(services, "obs_change_scene", {"scene": "BRB"}, label="BRB")
    game = add(services, "obs_change_scene", {"scene": "Gameplay"}, label="Game")

    async def scenario(svc):
        fake = await FakeObs().start()
        try:
            await connect(svc, fake)
            await svc.state_coordinator.refresh()
            assert services.states.get(game.id).state == "active"
            await svc.engine.execute_button(brb.id, "dev")
            await wait_for(lambda: svc.states.get(brb.id).state == "active" and svc.states.get(game.id).state == "inactive")
            # Someone switches scene in OBS itself: keys follow the event, no press, no polling.
            fake.scene = "Gameplay"
            await fake.emit("CurrentProgramSceneChanged", {"sceneName": "Gameplay"})
            await wait_for(lambda: svc.states.get(game.id).state == "active")
        finally:
            await fake.stop()

    run(services, scenario)


def test_toggle_source_camera_and_microphone(services) -> None:
    overlay = add(services, "obs_toggle_source", {"source": "Overlay"})
    cam = add(services, "obs_toggle_camera", {"scene": "BRB", "source": "Webcam"})
    mic = add(services, "obs_toggle_microphone", {"input": "Mic/Aux"})
    missing = add(services, "obs_toggle_source", {"source": "Deleted source"})

    async def scenario(svc):
        fake = await FakeObs().start()
        try:
            await connect(svc, fake)
            await svc.state_coordinator.refresh()
            assert (text(svc, overlay), text(svc, cam), text(svc, mic)) == ("Visible", "Camera off", "Live")
            await svc.engine.execute_button(overlay.id, "dev")
            await svc.engine.execute_button(cam.id, "dev")
            await svc.engine.execute_button(mic.id, "dev")
            await wait_for(lambda: (text(svc, overlay), text(svc, cam), text(svc, mic)) == ("Hidden", "Camera on", "Muted"))
            assert fake.items[("Gameplay", "Overlay")][1] is False and fake.muted["Mic/Aux"] is True
            # Muted from OBS's own mixer: the key follows.
            fake.muted["Mic/Aux"] = False
            await fake.emit("InputMuteStateChanged", {"inputName": "Mic/Aux", "inputMuted": False})
            await wait_for(lambda: text(svc, mic) == "Live")
            assert text(svc, missing) == "Not found"
            with pytest.raises(ActionError) as exc:
                await svc.engine.execute_button(missing.id, "dev")
            assert exc.value.code == "OBS_NOT_FOUND"
        finally:
            await fake.stop()

    run(services, scenario)


def test_keys_show_obs_offline_and_actions_explain(services) -> None:
    start = add(services, "obs_start_streaming")

    async def scenario(svc):
        await svc.state_coordinator.refresh()
        assert text(svc, start) == "OBS offline"
        with pytest.raises(ActionError) as exc:
            await svc.engine.execute_button(start.id, "dev")
        assert exc.value.code == "OBS_NOT_CONNECTED" and "Integrations" in exc.value.message

    run(services, scenario)


def test_obs_settings_api_keeps_password_secret(client, services) -> None:
    response = client.put("/api/admin/obs", json={"enabled": False, "host": "127.0.0.1", "port": 4455,
                                                  "password": "hunter2"})
    body = response.json()
    assert body["settings"] == {"enabled": False, "host": "127.0.0.1", "port": 4455, "hasPassword": True}
    assert "hunter2" not in response.text
    stored = services.settings.get("obs.password_dpapi")
    assert stored and "hunter2" not in stored  # encrypted with Windows DPAPI
    from opendeck.services.obs_settings import load_obs_settings
    assert load_obs_settings(services.settings).password == "hunter2"
    # null keeps the stored password; "" clears it
    client.put("/api/admin/obs", json={"enabled": False, "host": "127.0.0.1", "port": 4455, "password": None})
    assert load_obs_settings(services.settings).password == "hunter2"
    client.put("/api/admin/obs", json={"enabled": False, "host": "127.0.0.1", "port": 4455, "password": ""})
    assert load_obs_settings(services.settings).password == ""
    assert client.put("/api/admin/obs", json={"enabled": True, "host": "bad host;rm", "port": 4455}).status_code == 422
    assert client.get("/api/admin/obs/scenes").json()["detail"]["code"] == "OBS_NOT_CONNECTED"
