"""System Monitoring: settings, change-based publishing, the WebSocket feed and monitor pages."""

from __future__ import annotations

import asyncio
import io
import json

import pytest
from fastapi.testclient import TestClient

from opendeck.server.http import create_app
from opendeck.services import monitoring as mon
from opendeck.services.config import ButtonInput, ConfigError, PageInput
from opendeck.services.monitoring import MonitoringService, MonitoringSettings, Sampler

from .conftest import hello


class FakeSampler:
    """Stands in for Windows: CPU climbs by one each read; everything else fixed."""

    reads = 0

    def __init__(self) -> None:
        self.cpu = 10.0

    def read(self) -> dict:
        FakeSampler.reads += 1
        self.cpu += 1
        return {
            "cpu": {"status": "ok", "usage": self.cpu},
            "memory": {"status": "ok", "usage": 50.0, "used": 8, "total": 16, "available": 8},
            "battery": {"status": "unsupported"},
            "cpuTemp": {"status": "unavailable"},
        }


class SteadySampler(FakeSampler):
    def read(self) -> dict:
        FakeSampler.reads += 1
        return {"cpu": {"status": "ok", "usage": 5.0}}


# ---- settings ------------------------------------------------------------------------------

def test_settings_validate_and_fill_in_new_metrics() -> None:
    with pytest.raises(ValueError):
        MonitoringSettings(interval_ms=250)
    s = MonitoringSettings(tiles=[{"metric": "ram", "enabled": False}, {"metric": "nope"}, {"metric": "ram"}])
    assert [t.metric for t in s.tiles][0] == "ram" and s.tiles[0].enabled is False
    assert sorted(t.metric for t in s.tiles) == sorted(mon.METRICS)  # unknown dropped, missing added


def test_settings_persist(services) -> None:
    services.monitoring.update_settings(MonitoringSettings(interval_ms=2000))
    assert mon.load_settings(services.settings).interval_ms == 2000


# ---- service ---------------------------------------------------------------------------------

def test_publishes_only_changes_plus_keepalive(services, monkeypatch) -> None:
    sent: list[dict] = []

    async def publish(payload):
        sent.append(payload)

    service = MonitoringService(services.settings, sampler_factory=SteadySampler)
    service.bind(publish, lambda: 1)

    async def scenario():
        for _ in range(3):
            await service._maybe_publish(await service.sample_once())
        assert len(sent) == 1  # identical readings are not resent
        monkeypatch.setattr(mon, "KEEPALIVE_S", 0.0)
        await service._maybe_publish(await service.sample_once())
        assert len(sent) == 2  # ...except as a keep-alive
        await service.stop()

    asyncio.run(scenario())


def test_samples_only_while_someone_watches(services) -> None:
    watchers = {"n": 0}
    sent: list[dict] = []

    async def publish(payload):
        sent.append(payload)

    service = MonitoringService(services.settings, sampler_factory=FakeSampler)
    service.bind(publish, lambda: watchers["n"])

    async def scenario():
        FakeSampler.reads = 0
        service.start()
        await asyncio.sleep(0.15)
        assert FakeSampler.reads == 0  # idle: Windows is not read at all
        watchers["n"] = 1
        service.wake()
        await asyncio.sleep(0.15)
        assert FakeSampler.reads == 1 and len(sent) == 1
        assert sent[0]["metrics"]["cpu"] == {"status": "ok", "usage": 11.0}
        assert sent[0]["intervalMs"] == 1000
        await service.stop()

    asyncio.run(scenario())


def test_one_failing_sensor_does_not_stop_the_others() -> None:
    assert Sampler._safe(lambda: 1 / 0) == {"status": "error"}
    assert Sampler._safe(lambda: {"status": "ok", "usage": 3}) == {"status": "ok", "usage": 3}


def test_back_to_back_reads_repeat_rates_instead_of_noise() -> None:
    calls = {"fast": 0}

    class Counting(Sampler):
        def _cpu(self):
            calls["fast"] += 1
            return {"status": "ok", "usage": float(calls["fast"])}

        _memory = _gpu = _network = lambda self: {"status": "ok"}
        _gpu_temperature = _cpu_temperature = _disks = _battery = _wifi = _internet = lambda self: {"status": "ok"}

    sampler = Counting()
    first = sampler.read()
    second = sampler.read()  # e.g. a device subscribing right after the regular tick
    assert calls["fast"] == 1 and first["cpu"] == second["cpu"]


def test_cpu_temperature_from_librehardwaremonitor(monkeypatch) -> None:
    tree = {"Text": "Sensor", "Children": [{"Text": "PC", "Children": [
        {"Text": "AMD Ryzen 7", "ImageURL": "images_icon/cpu.png", "Children": [
            {"Text": "Temperatures", "Children": [
                {"Text": "Core (Tctl/Tdie)", "Value": "61,5 °C", "Children": []},
                {"Text": "CCD1 (Tdie)", "Value": "58.0 °C", "Children": []},
            ]},
            {"Text": "Load", "Children": [{"Text": "CPU Total", "Value": "12.0 %", "Children": []}]},
        ]},
        {"Text": "NVIDIA", "ImageURL": "images_icon/nvidia.png", "Children": [
            {"Text": "Temperatures", "Children": [{"Text": "GPU Core", "Value": "50.0 °C", "Children": []}]},
        ]},
    ]}]}
    monkeypatch.setattr(mon.urllib.request, "urlopen",
                        lambda url, timeout: io.BytesIO(json.dumps(tree).encode()))
    assert mon._lhm_cpu_temperature() == 61.5

    def refuse(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(mon.urllib.request, "urlopen", refuse)
    assert mon._lhm_cpu_temperature() is None  # not running: N/A, never a made-up value


# ---- pages -------------------------------------------------------------------------------------

def test_monitor_page_is_seeded_once_and_has_no_buttons(services) -> None:
    monitor = [p for p in services.pages.list_all() if p.kind == "monitor"]
    assert [p.name for p in monitor] == ["System Monitoring"]
    mon_seed = __import__("opendeck.services.seed", fromlist=["seed_monitor_page"])
    services.pages.delete(monitor[0].id)
    mon_seed.seed_monitor_page(services.settings, services.pages)  # the user deleted it: stays deleted
    assert not any(p.kind == "monitor" for p in services.pages.list_all())

    cfg = services.deck_config
    page = cfg.create_page(services.profiles.list()[0].id, PageInput(name="Stats", kind="monitor"))
    with pytest.raises(ConfigError) as exc:
        cfg.create_button(page.id, ButtonInput(label="x", action_type="media_play_pause"))
    assert exc.value.code == "NOT_A_DECK_PAGE"
    lock = services.buttons.list_all()[0]
    with pytest.raises(ConfigError):
        cfg.move_button(lock.id, page.id)
    assert cfg.duplicate_page(page.id).kind == "monitor"
    snap_pages = {p["id"]: p for p in services.snapshots.build()["pages"]}
    assert snap_pages[page.id]["kind"] == "monitor"


# ---- API and WebSocket -----------------------------------------------------------------------

def test_admin_monitoring_settings_and_live_preview(services) -> None:
    services.monitoring.sampler_factory = FakeSampler
    client = TestClient(create_app(services))
    body = client.get("/api/admin/monitoring").json()
    assert body["settings"]["intervalMs"] == 1000 and len(body["metrics"]) == 12
    tiles = [{"metric": m, "enabled": m != "battery"} for m in body["metrics"]]
    saved = client.put("/api/admin/monitoring", json={"intervalMs": 2000, "tiles": tiles})
    assert saved.status_code == 200 and saved.json()["settings"]["intervalMs"] == 2000
    assert client.put("/api/admin/monitoring", json={"intervalMs": 10}).status_code == 422
    live = client.get("/api/admin/monitoring/live").json()
    assert live["metrics"]["cpu"]["status"] == "ok" and live["intervalMs"] == 2000


def test_websocket_feed_reaches_subscribed_devices(services) -> None:
    services.monitoring.sampler_factory = FakeSampler
    with TestClient(create_app(services)) as client:
        code, _ = services.pairing.current_code()
        token = client.post("/api/pair", json={"code": code, "deviceName": "iPad"}).json()["token"]
        with client.websocket_connect("/ws") as ws:
            ws.send_json(hello(token))
            assert ws.receive_json()["type"] == "WELCOME"
            snapshot = ws.receive_json()
            assert any(p["kind"] == "monitor" for p in snapshot["payload"]["pages"])
            assert services.hub.monitor_watchers() == 0
            ws.send_json({"version": 2, "type": "MONITOR_SUBSCRIBE", "payload": {"active": True}})
            update = ws.receive_json()
            assert update["type"] == "SYSTEM_MONITOR"
            assert update["payload"]["metrics"]["cpu"]["status"] == "ok"
            assert update["payload"]["metrics"]["battery"] == {"status": "unsupported"}
            assert services.hub.monitor_watchers() == 1
            ws.send_json({"version": 2, "type": "MONITOR_SUBSCRIBE", "payload": {"active": False}})
            ws.send_json({"version": 2, "type": "PING", "requestId": "p"})
            while (msg := ws.receive_json())["type"] != "PONG":
                pass
            assert services.hub.monitor_watchers() == 0
