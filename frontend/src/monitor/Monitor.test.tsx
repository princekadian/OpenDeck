import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeckStore, nextMonitor } from "../connection/deckStore";
import { Dashboard } from "../dashboard/Dashboard";
import type { MonitorMetrics, SystemMonitorPayload } from "../protocol/messages";
import { FakeSocket, createFakeSocket, lockButton, page, profile, welcomeAndSnapshot } from "../test/fakeSocket";
import { bitRate, buildTiles, levelFor } from "./tiles";

Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1132 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 648 });

const ALL = ["cpu", "gpu", "ram", "cpu_temp", "gpu_temp", "net_up", "net_down", "disk", "disk_temp", "battery", "wifi", "internet"] as const;

function payload(metrics: MonitorMetrics, timestamp = 1): SystemMonitorPayload {
  return { timestamp, intervalMs: 1000, tiles: [...ALL], metrics };
}

const desktop: MonitorMetrics = {
  cpu: { status: "ok", usage: 37.4 },
  gpu: { status: "ok", usage: 92, name: "NVIDIA GeForce RTX 5060" },
  memory: { status: "ok", usage: 62, used: 9.9 * 1024 ** 3, total: 16 * 1024 ** 3 },
  cpuTemp: { status: "unavailable" },
  gpuTemp: { status: "ok", celsius: 64.2, name: "NVIDIA GeForce RTX 5060" },
  network: { status: "ok", interface: "Wi-Fi", kind: "wifi", connected: true, upBytesPerSec: 1_550_000, downBytesPerSec: 10_525_000 },
  disks: {
    status: "ok",
    drives: [
      { drive: "C:", usage: 71, used: 710e9, total: 1000e9, free: 290e9, disk: 1, celsius: 42 },
      { drive: "D:", usage: 10, used: 10e9, total: 100e9, free: 90e9, disk: 1, celsius: 42 },
      { drive: "E:", usage: 27, used: 270e9, total: 1000e9, free: 730e9, disk: 0, celsius: null },
    ],
  },
  battery: { status: "unsupported" },
  wifi: { status: "ok", connected: true, ssid: "Home", signal: 82 },
  internet: { status: "ok", connected: true },
};

describe("monitoring tiles", () => {
  it("shows real values and N/A without ever inventing a reading", () => {
    const tiles = Object.fromEntries(buildTiles(payload(desktop)).map((t) => [t.key, t]));
    expect(tiles.cpu.value).toBe("37%");
    expect(tiles.gpu).toMatchObject({ value: "92%", level: "high", detail: "RTX 5060" });
    expect(tiles.ram).toMatchObject({ value: "62%", detail: "9.9 / 16.0 GB" });
    expect(tiles.cpu_temp).toMatchObject({ value: "N/A", status: "unavailable", level: null });
    expect(tiles.gpu_temp.value).toBe("64°C");
    expect(tiles.net_down.value).toBe("↓ 84.2 Mbps");
    expect(tiles.net_up.value).toBe("↑ 12.4 Mbps");
    expect(tiles["disk:C:"]).toMatchObject({ value: "71%", title: "Disk C:" });
    // One temperature tile per physical disk; a disk that doesn't report it says so.
    expect(tiles["disk_temp:disk:1"]).toMatchObject({ value: "42°C", title: "Disk temp C: D:" });
    expect(tiles["disk_temp:disk:0"]).toMatchObject({ value: "N/A", detail: "Disk doesn't report it" });
    expect(tiles.battery).toMatchObject({ value: "N/A", detail: "No battery" });
    expect(tiles.wifi).toMatchObject({ value: "Connected", detail: "Home · Signal 82%" });
    expect(tiles.internet.value).toBe("Online");
  });

  it("says Ethernet instead of claiming Wi-Fi, and tells offline from disconnected", () => {
    const wired = payload({ ...desktop, network: { status: "ok", kind: "ethernet", interface: "Ethernet", connected: true, upBytesPerSec: 0, downBytesPerSec: 0 }, internet: { status: "ok", connected: false } });
    const tiles = Object.fromEntries(buildTiles(wired).map((t) => [t.key, t]));
    expect(tiles.wifi).toMatchObject({ title: "Network", value: "Ethernet" });
    expect(tiles.internet).toMatchObject({ value: "Offline", level: "high" });
  });

  it("formats speeds and applies thresholds", () => {
    expect(bitRate(100)).toBe("800 bps");
    expect(bitRate(125_000)).toBe("1.0 Mbps");
    expect(levelFor("cpu", 50)).toBe("normal");
    expect(levelFor("cpu", 75)).toBe("warn");
    expect(levelFor("battery", 15)).toBe("warn");
    expect(levelFor("battery", 5)).toBe("high");
  });

  it("keeps a short history and ignores keep-alive repeats", () => {
    let view = nextMonitor(null, payload(desktop, 1));
    view = nextMonitor(view, payload({ ...desktop, cpu: { status: "ok", usage: 50 } }, 2));
    view = nextMonitor(view, payload({ ...desktop, cpu: { status: "ok", usage: 50 } }, 2));
    expect(view.history.cpu).toEqual([37.4, 50]);
  });
});

describe("System Monitoring page on a device", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    localStorage.clear();
  });
  afterEach(() => vi.useRealTimers());

  const monitorPage = { id: "m1", profileId: "pr", name: "System Monitoring", iconRef: null, sortOrder: 1, kind: "monitor" };

  function setup() {
    const store = new DeckStore("t".repeat(43), vi.fn(), { createSocket: createFakeSocket }, null);
    render(<Dashboard token="x" onUnauthorized={vi.fn()} store={store} />);
    const socket = FakeSocket.latest();
    act(() => welcomeAndSnapshot(socket, { profiles: [profile], pages: [page, monitorPage], buttons: [lockButton] }));
    return socket;
  }

  const subscriptions = (socket: FakeSocket) => socket.sent.filter((m) => m.type === "MONITOR_SUBSCRIBE").map((m) => m.payload.active);

  it("subscribes only while the page is shown and draws the readings", () => {
    const socket = setup();
    expect(subscriptions(socket)).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "System Monitoring" }));
    expect(subscriptions(socket)).toEqual([true]);
    expect(screen.getByText("Reading this PC's sensors…")).toBeInTheDocument();

    act(() => socket.serverSend({ type: "SYSTEM_MONITOR", payload: payload(desktop) }));
    expect(screen.getByRole("article", { name: "CPU: 37%, Utilization" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: /^CPU temp: N\/A/ })).toBeInTheDocument();
    expect(screen.getByText("Live · every 1 s")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Main" }));
    expect(subscriptions(socket)).toEqual([true, false]);
  });

  it("marks values stale when the connection drops and resubscribes on reconnect", () => {
    const socket = setup();
    fireEvent.click(screen.getByRole("button", { name: "System Monitoring" }));
    act(() => socket.serverSend({ type: "SYSTEM_MONITOR", payload: payload(desktop) }));
    act(() => socket.serverClose(1006));
    expect(screen.getByText("Connection lost · reconnecting…")).toBeInTheDocument();
    expect(document.querySelector(".monitor__grid")).toHaveAttribute("data-stale");

    act(() => vi.advanceTimersByTime(500));
    const next = FakeSocket.latest();
    act(() => welcomeAndSnapshot(next, { profiles: [profile], pages: [page, monitorPage], buttons: [lockButton] }));
    expect(subscriptions(next)).toEqual([true]);
  });
});
