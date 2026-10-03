"""System Monitoring: one sampler on the PC feeds every device that shows the page.

Layout:
- `Sampler` reads Windows on one dedicated worker thread (COM, PDH and wlanapi handles
  are created and used there only). Each metric is read by its own small function, so one
  failing sensor never stops the others.
- `MonitoringService` runs the sampling loop only while someone watches (a device with a
  monitoring page open, or the editor preview), and hands each new reading to `publish`
  only when it differs from the last one (plus a keep-alive), so idle values cost nothing.

Readings live in memory only. Settings (interval, which tiles) are stored as JSON in
the settings table under `monitoring`.

Every metric reports a `status`:
  ok           value present
  unavailable  the hardware exists but doesn't report this (e.g. a SATA disk's temperature)
  unsupported  this PC has no such hardware (no battery, no Wi-Fi adapter)
  error        reading failed this time
  unknown      not read yet
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from ..repositories import SettingsRepository

log = logging.getLogger(__name__)

SETTINGS_KEY = "monitoring"
METRICS = ("cpu", "gpu", "ram", "cpu_temp", "gpu_temp", "net_up", "net_down", "disk", "disk_temp",
           "battery", "wifi", "internet")
INTERVALS_MS = (1000, 2000, 5000)
# Slow-changing readings (temperatures, Wi-Fi, Internet, drive space) refresh at most this often.
SLOW_EVERY_S = 5.0
# Resend unchanged data this often so devices can tell "steady" from "stale".
KEEPALIVE_S = 5.0
# How long an editor preview request keeps sampling alive.
PREVIEW_LEASE_S = 6.0
# Optional CPU temperature source: LibreHardwareMonitor's "Remote web server" on this PC.
LHM_URL = "http://127.0.0.1:8085/data.json"
LHM_RETRY_S = 30.0
# Rates (network) need at least this much time between readings to mean anything.
MIN_RATE_WINDOW_S = 0.25

Status = Literal["ok", "unavailable", "unsupported", "error", "unknown"]


# ---- settings -------------------------------------------------------------------------------

class TileSetting(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    metric: str
    enabled: bool = True


class MonitoringSettings(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")
    interval_ms: int = 1000
    # Order and visibility of tiles on monitoring pages.
    tiles: list[TileSetting] = Field(default_factory=lambda: [TileSetting(metric=m) for m in METRICS])

    @field_validator("interval_ms")
    @classmethod
    def _interval(cls, value: int) -> int:
        if value not in INTERVALS_MS:
            raise ValueError(f"Choose one of {', '.join(str(i // 1000) for i in INTERVALS_MS)} seconds.")
        return value

    @field_validator("tiles")
    @classmethod
    def _tiles(cls, tiles: list[TileSetting]) -> list[TileSetting]:
        seen: set[str] = set()
        out: list[TileSetting] = []
        for tile in tiles:
            if tile.metric in METRICS and tile.metric not in seen:
                seen.add(tile.metric)
                out.append(tile)
        # Metrics added in later versions appear at the end, switched on.
        out += [TileSetting(metric=m) for m in METRICS if m not in seen]
        return out


def load_settings(settings: SettingsRepository) -> MonitoringSettings:
    raw = settings.get(SETTINGS_KEY)
    if not raw:
        return MonitoringSettings()
    try:
        return MonitoringSettings.model_validate_json(raw)
    except ValueError:
        log.warning("Monitoring settings were unreadable; using defaults")
        return MonitoringSettings()


def save_settings(settings: SettingsRepository, value: MonitoringSettings) -> None:
    settings.set(SETTINGS_KEY, value.model_dump_json(by_alias=True))


# ---- sampling (runs on the worker thread) -----------------------------------------------------

def _metric(status: Status, **values: Any) -> dict[str, Any]:
    return {"status": status, **values}


class Sampler:
    """Reads Windows. Every public method runs on the sampler thread only."""

    def __init__(self) -> None:
        from ..native.windows import com

        com.init_thread()
        self._cpu_before = None
        self._net_before: tuple[int, int, int, float] | None = None  # index, rx, tx, time
        self._fast: dict[str, dict[str, Any]] = {}
        self._fast_at = 0.0
        self._gpu_usage = None
        self._gpus: list | None = None
        self._wlan = None
        self._nlm = None
        self._slow: dict[str, dict[str, Any]] = {}
        self._slow_at = 0.0
        self._lhm_retry_at = 0.0

    def read(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._slow_at >= SLOW_EVERY_S or not self._slow:
            self._slow_at = now
            self._slow = {
                "gpuTemp": self._safe(self._gpu_temperature),
                "cpuTemp": self._safe(self._cpu_temperature),
                "disks": self._safe(self._disks),
                "battery": self._safe(self._battery),
                "wifi": self._safe(self._wifi),
                "internet": self._safe(self._internet),
            }
        # Rates (CPU, GPU, network) need time between readings; a read that follows
        # another within MIN_RATE_WINDOW_S repeats it instead of reporting noise.
        if now - self._fast_at >= MIN_RATE_WINDOW_S or not self._fast:
            self._fast_at = now
            self._fast = {
                "cpu": self._safe(self._cpu),
                "memory": self._safe(self._memory),
                "gpu": self._safe(self._gpu),
                "network": self._safe(self._network),
            }
        return {**self._fast, **self._slow}

    @staticmethod
    def _safe(read: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return read()
        except Exception as exc:  # one sensor must never stop the others
            log.debug("Monitoring read %s failed: %s", getattr(read, "__name__", read), exc)
            return _metric("error")

    # -- fast metrics

    def _cpu(self) -> dict[str, Any]:
        from ..native.windows import sysinfo

        now = sysinfo.cpu_times()
        before, self._cpu_before = self._cpu_before, now
        usage = sysinfo.cpu_usage(before, now) if before else None
        return _metric("ok", usage=round(usage, 1)) if usage is not None else _metric("unknown")

    def _memory(self) -> dict[str, Any]:
        from ..native.windows import sysinfo

        mem = sysinfo.memory()
        used = mem.total - mem.available
        return _metric("ok", usage=round(100 * used / mem.total, 1), used=used, total=mem.total,
                       available=mem.available)

    def _gpu_adapters(self) -> list:
        from ..native.windows import gpu

        if self._gpus is None:
            self._gpus = gpu.hardware_adapters()
        return self._gpus

    def _gpu(self) -> dict[str, Any]:
        from ..native.windows import gpu

        adapters = self._gpu_adapters()
        if not adapters:
            return _metric("unsupported")
        if self._gpu_usage is None:
            self._gpu_usage = gpu.GpuUsageSampler()
            return _metric("unknown", name=adapters[0].name)
        usage = self._gpu_usage.sample()
        # Drivers can expose one GPU under two LUIDs; keep those that run engines.
        listed = [a for a in adapters if a.luid in usage] or adapters
        out = [{"id": a.luid, "name": a.name, "usage": round(usage.get(a.luid, 0.0), 1)} for a in listed]
        return _metric("ok", name=out[0]["name"], usage=out[0]["usage"], adapters=out)

    def _network(self) -> dict[str, Any]:
        from ..native.windows import network

        index = network.default_interface_index()
        info = network.interface(index) if index is not None else None
        if info is None or not info.up:
            self._net_before = None
            return _metric("unavailable", connected=False)
        now = time.monotonic()
        before = self._net_before
        kind = "wifi" if info.wireless else "ethernet"
        base = {"interface": info.name, "kind": kind, "linkBps": info.link_bps, "connected": True}
        self._net_before = (info.index, info.rx_bytes, info.tx_bytes, now)
        if not before or before[0] != info.index or now <= before[3]:
            return _metric("unknown", **base)
        seconds = now - before[3]
        down = max(0, info.rx_bytes - before[1]) / seconds
        up = max(0, info.tx_bytes - before[2]) / seconds
        return _metric("ok", downBytesPerSec=round(down), upBytesPerSec=round(up), **base)

    # -- slow metrics

    def _gpu_temperature(self) -> dict[str, Any]:
        from ..native.windows import gpu

        adapters = self._gpu_adapters()
        if not adapters:
            return _metric("unsupported")
        temps = gpu.temperatures()
        for adapter in adapters:
            if adapter.luid in temps:
                return _metric("ok", celsius=round(temps[adapter.luid], 1), name=adapter.name)
        return _metric("unavailable", name=adapters[0].name)

    def _cpu_temperature(self) -> dict[str, Any]:
        """Windows has no vendor-neutral CPU temperature API for normal apps. The ACPI
        "thermal zone" is often a fixed firmware placeholder, so it is not used. When
        LibreHardwareMonitor runs with its web server on, its CPU package reading is used."""
        now = time.monotonic()
        if now < self._lhm_retry_at:
            return _metric("unavailable")
        celsius = _lhm_cpu_temperature()
        if celsius is None:
            self._lhm_retry_at = now + LHM_RETRY_S
            return _metric("unavailable")
        return _metric("ok", celsius=round(celsius, 1), source="LibreHardwareMonitor")

    def _disks(self) -> dict[str, Any]:
        from ..native.windows import storage

        drives = []
        temps: dict[int, float | None] = {}
        for d in storage.fixed_drives():
            number = storage.disk_number(d.drive)
            if number is not None and number not in temps:
                temps[number] = storage.disk_temperature(number)
            used = d.total - d.free
            drives.append({"drive": d.drive, "usage": round(100 * used / d.total, 1), "used": used,
                           "total": d.total, "free": d.free, "disk": number,
                           "celsius": temps.get(number) if number is not None else None})
        if not drives:
            return _metric("unavailable", drives=[])
        return _metric("ok", drives=drives)

    def _battery(self) -> dict[str, Any]:
        from ..native.windows import sysinfo

        battery = sysinfo.battery()
        if battery is None:
            return _metric("unsupported")
        if battery.percent is None:
            return _metric("unavailable")
        return _metric("ok", percent=battery.percent, charging=battery.charging, pluggedIn=battery.plugged_in)

    def _wifi(self) -> dict[str, Any]:
        from ..native.windows import network

        if self._wlan is None:
            self._wlan = network.WlanClient()
        info = self._wlan.wifi()
        if info is None:
            return _metric("unsupported")
        return _metric("ok", connected=info.connected, ssid=info.ssid, signal=info.signal,
                       rxKbps=info.rx_kbps)

    def _internet(self) -> dict[str, Any]:
        from ..native.windows import network

        if self._nlm is None:
            self._nlm = network.network_list_manager()
        return _metric("ok", connected=network.internet_connected(self._nlm))


def _lhm_cpu_temperature() -> float | None:
    """CPU package temperature from LibreHardwareMonitor's local JSON, if it is running."""
    try:
        with urllib.request.urlopen(LHM_URL, timeout=0.3) as response:
            tree = json.load(response)
    except (OSError, ValueError):
        return None
    preferred = ("cpu package", "core (tctl/tdie)", "tctl/tdie", "package", "core average", "core max")
    found: dict[str, float] = {}

    def walk(node: dict[str, Any], in_cpu: bool, in_temps: bool) -> None:
        text = str(node.get("Text", ""))
        image = str(node.get("ImageURL", ""))
        cpu = in_cpu or "cpu" in image.lower()
        temps = in_temps or text.lower() == "temperatures"
        value = str(node.get("Value", ""))
        if cpu and temps and "°C" in value:
            try:
                found[text.lower()] = float(value.split()[0].replace(",", "."))
            except ValueError:
                pass
        for child in node.get("Children", []) or []:
            walk(child, cpu, temps)

    walk(tree, False, False)
    for name in preferred:
        if name in found:
            return found[name]
    return None


# ---- service (event loop side) ------------------------------------------------------------

Publish = Callable[[dict[str, Any]], Awaitable[None]]


class MonitoringService:
    def __init__(self, settings: SettingsRepository, sampler_factory: Callable[[], Sampler] = Sampler) -> None:
        self._settings_repo = settings
        self.settings = load_settings(settings)
        self.sampler_factory = sampler_factory
        self._sampler: Sampler | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="monitor")
        self._publish: Publish | None = None
        self._watchers: Callable[[], int] = lambda: 0
        self._lease_until = 0.0
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.latest: dict[str, Any] | None = None
        self._last_sent_key: str | None = None
        self._last_sent_at = 0.0

    def bind(self, publish: Publish, watchers: Callable[[], int]) -> None:
        """`publish` sends a payload to watching devices; `watchers` counts them."""
        self._publish = publish
        self._watchers = watchers

    def update_settings(self, value: MonitoringSettings) -> MonitoringSettings:
        save_settings(self._settings_repo, value)
        self.settings = value
        self._last_sent_key = None  # devices get the new interval with the next reading
        self.wake()
        return value

    def wake(self) -> None:
        """Someone started watching: sample now instead of waiting for the next tick."""
        self._wake.set()

    def lease(self) -> None:
        """Keep sampling briefly without a device (the editor preview polls this)."""
        idle = not self._active()
        self._lease_until = time.monotonic() + PREVIEW_LEASE_S
        if idle:
            self.wake()  # only start an idle loop; never add extra reads to a running one

    def _active(self) -> bool:
        return self._watchers() > 0 or time.monotonic() < self._lease_until

    def start(self) -> None:
        if self._task is None:
            self._wake = asyncio.Event()
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def sample_once(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        metrics = await loop.run_in_executor(self._executor, self._read)
        self.latest = {"timestamp": int(time.time() * 1000), "intervalMs": self.settings.interval_ms,
                       # Tiles to show, in order; devices draw exactly these.
                       "tiles": [t.metric for t in self.settings.tiles if t.enabled],
                       "metrics": metrics}
        return self.latest

    def _read(self) -> dict[str, Any]:
        if self._sampler is None:
            self._sampler = self.sampler_factory()
        return self._sampler.read()

    async def _run(self) -> None:
        while True:
            if not self._active():
                self._wake.clear()
                await self._wake.wait()  # idle: no device watching, no sampling at all
                continue
            started = time.monotonic()
            try:
                payload = await self.sample_once()
                await self._maybe_publish(payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Monitoring sample failed")
            self._wake.clear()
            delay = max(0.05, self.settings.interval_ms / 1000 - (time.monotonic() - started))
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except asyncio.TimeoutError:
                pass

    async def _maybe_publish(self, payload: dict[str, Any]) -> None:
        if self._publish is None or self._watchers() == 0:
            return
        key = json.dumps([payload["intervalMs"], payload["tiles"], payload["metrics"]], sort_keys=True)
        now = time.monotonic()
        if key == self._last_sent_key and now - self._last_sent_at < KEEPALIVE_S:
            return  # nothing changed
        self._last_sent_key, self._last_sent_at = key, now
        await self._publish(payload)

    def recent(self) -> dict[str, Any] | None:
        """The latest reading if it is still current (younger than two intervals)."""
        if self.latest is None:
            return None
        age_ms = time.time() * 1000 - self.latest["timestamp"]
        return self.latest if age_ms <= 2 * self.settings.interval_ms + 1000 else None

    def forget_last_sent(self) -> None:
        """A device subscribed: make sure the next reading goes out even if unchanged."""
        self._last_sent_key = None
        self.wake()
