// System Monitoring tiles: turns one reading from the PC into display tiles.
// Pure functions, shared by the device dashboard and the editor preview.

import type { MetricStatus, MonitorMetricId, MonitorMetrics, SystemMonitorPayload } from "../protocol/messages";

/** normal / warn / high drive a quiet colour change; never flashing. */
export type Level = "normal" | "warn" | "high";

export interface Tile {
  /** Unique per tile ("disk:C:"), stable across readings. */
  key: string;
  metric: MonitorMetricId;
  title: string;
  icon: string;
  /** Main reading, e.g. "37%", "58°C", "N/A". */
  value: string;
  /** Second line: detail or why there is no value. */
  detail: string;
  status: MetricStatus;
  level: Level | null;
  /** Key into MonitorView.history for a sparkline. */
  history?: string;
  /** Upper bound for the sparkline (100 for percentages); undefined = scale to the data. */
  historyMax?: number;
}

/** Default thresholds; the data model keeps them per metric so they can become settings. */
export const THRESHOLDS: Partial<Record<MonitorMetricId, { warn: number; high: number; below?: boolean }>> = {
  cpu: { warn: 70, high: 90 },
  gpu: { warn: 70, high: 90 },
  ram: { warn: 80, high: 90 },
  disk: { warn: 85, high: 95 },
  cpu_temp: { warn: 80, high: 90 },
  gpu_temp: { warn: 80, high: 87 },
  disk_temp: { warn: 60, high: 70 },
  battery: { warn: 20, high: 10, below: true },
};

export const METRIC_LABELS: Record<MonitorMetricId, string> = {
  cpu: "CPU usage",
  gpu: "GPU usage",
  ram: "Memory (RAM)",
  cpu_temp: "CPU temperature",
  gpu_temp: "GPU temperature",
  net_up: "Upload speed",
  net_down: "Download speed",
  disk: "Disk usage",
  disk_temp: "Disk temperature",
  battery: "Battery",
  wifi: "Wi-Fi",
  internet: "Internet",
};

export function levelFor(metric: MonitorMetricId, value: number | undefined | null): Level | null {
  const t = THRESHOLDS[metric];
  if (!t || value === undefined || value === null) return null;
  if (t.below) return value <= t.high ? "high" : value <= t.warn ? "warn" : "normal";
  return value >= t.high ? "high" : value >= t.warn ? "warn" : "normal";
}

// ---- formatting -------------------------------------------------------------------------

export const percent = (v: number) => `${Math.round(v)}%`;
export const celsius = (v: number) => `${Math.round(v)}°C`;

export function gigabytes(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  if (gb >= 1000) return `${(gb / 1024).toFixed(gb >= 10240 ? 0 : 1)} TB`;
  return `${gb >= 100 ? Math.round(gb) : gb.toFixed(1)} GB`;
}

/** Network speed in bits per second, as ISPs and speed tests show it. */
export function bitRate(bytesPerSec: number): string {
  const bits = bytesPerSec * 8;
  if (bits >= 1e9) return `${(bits / 1e9).toFixed(2)} Gbps`;
  if (bits >= 1e6) return `${(bits / 1e6).toFixed(bits >= 1e8 ? 0 : 1)} Mbps`;
  if (bits >= 1e3) return `${Math.round(bits / 1e3)} Kbps`;
  return `${Math.round(bits)} bps`;
}

/** The same speed in bytes, as download managers show it. */
export function byteRate(bytesPerSec: number): string {
  if (bytesPerSec >= 1024 ** 2) return `${(bytesPerSec / 1024 ** 2).toFixed(1)} MB/s`;
  if (bytesPerSec >= 1024) return `${Math.round(bytesPerSec / 1024)} KB/s`;
  return `${Math.round(bytesPerSec)} B/s`;
}

const NO_VALUE: Record<MetricStatus, string> = {
  ok: "",
  unavailable: "Not reported by this PC",
  unsupported: "Not on this PC",
  error: "Couldn't read",
  unknown: "Measuring…",
};

function missing(base: Omit<Tile, "value" | "detail" | "level" | "status">, status: MetricStatus, detail?: string): Tile {
  return { ...base, status, value: status === "unknown" ? "…" : "N/A", detail: detail ?? NO_VALUE[status], level: null };
}

// ---- tiles ------------------------------------------------------------------------------

export function buildTiles(payload: SystemMonitorPayload): Tile[] {
  const m = payload.metrics;
  return payload.tiles.flatMap((metric) => tilesFor(metric, m));
}

function tilesFor(metric: MonitorMetricId, m: MonitorMetrics): Tile[] {
  switch (metric) {
    case "cpu": {
      const base = { key: "cpu", metric, title: "CPU", icon: "cpu", history: "cpu", historyMax: 100 };
      const c = m.cpu;
      if (c?.status !== "ok" || c.usage === undefined) return [missing(base, c?.status ?? "unknown")];
      return [{ ...base, status: "ok", value: percent(c.usage), detail: "Utilization", level: levelFor(metric, c.usage) }];
    }
    case "gpu": {
      const base = { key: "gpu", metric, title: "GPU", icon: "gpu", history: "gpu", historyMax: 100 };
      const g = m.gpu;
      if (g?.status !== "ok" || g.usage === undefined) return [missing(base, g?.status ?? "unknown", g?.name)];
      return [{ ...base, status: "ok", value: percent(g.usage), detail: shortGpu(g.name) || "Utilization", level: levelFor(metric, g.usage) }];
    }
    case "ram": {
      const base = { key: "ram", metric, title: "RAM", icon: "memory", history: "ram", historyMax: 100 };
      const r = m.memory;
      if (r?.status !== "ok" || r.usage === undefined) return [missing(base, r?.status ?? "unknown")];
      const detail = r.used !== undefined && r.total ? `${gigabytes(r.used).replace(" GB", "")} / ${gigabytes(r.total)}` : "In use";
      return [{ ...base, status: "ok", value: percent(r.usage), detail, level: levelFor(metric, r.usage) }];
    }
    case "cpu_temp": {
      const base = { key: "cpu_temp", metric, title: "CPU temp", icon: "thermometer" };
      const t = m.cpuTemp;
      if (t?.status !== "ok" || t.celsius === undefined) {
        const why = t?.status === "unavailable" ? "No sensor access" : undefined;
        return [missing(base, t?.status ?? "unknown", why)];
      }
      return [{ ...base, status: "ok", value: celsius(t.celsius), detail: "Package", level: levelFor(metric, t.celsius) }];
    }
    case "gpu_temp": {
      const base = { key: "gpu_temp", metric, title: "GPU temp", icon: "thermometer" };
      const t = m.gpuTemp;
      if (t?.status !== "ok" || t.celsius === undefined) return [missing(base, t?.status ?? "unknown")];
      return [{ ...base, status: "ok", value: celsius(t.celsius), detail: shortGpu(t.name) || "Core", level: levelFor(metric, t.celsius) }];
    }
    case "net_up":
    case "net_down": {
      const up = metric === "net_up";
      const base = { key: metric, metric, title: up ? "Upload" : "Download", icon: up ? "upload" : "download", history: metric };
      const n = m.network;
      if (n?.status === "unavailable") return [missing(base, "unavailable", "No network connection")];
      const rate = up ? n?.upBytesPerSec : n?.downBytesPerSec;
      if (n?.status !== "ok" || rate === undefined) return [missing(base, n?.status ?? "unknown")];
      return [{ ...base, status: "ok", value: `${up ? "↑" : "↓"} ${bitRate(rate)}`, detail: `${byteRate(rate)} · ${n.interface ?? ""}`.replace(/ · $/, ""), level: null }];
    }
    case "disk": {
      const d = m.disks;
      if (d?.status !== "ok" || !d.drives?.length) {
        return [missing({ key: "disk", metric, title: "Disk", icon: "disk" }, d?.status ?? "unknown")];
      }
      return d.drives.map((drive) => ({
        key: `disk:${drive.drive}`,
        metric,
        title: `Disk ${drive.drive}`,
        icon: "disk",
        status: "ok" as const,
        value: percent(drive.usage),
        detail: `${gigabytes(drive.used).replace(/ (GB|TB)$/, "")} / ${gigabytes(drive.total)}`,
        level: levelFor(metric, drive.usage),
      }));
    }
    case "disk_temp": {
      const d = m.disks;
      if (d?.status !== "ok" || !d.drives?.length) {
        return [missing({ key: "disk_temp", metric, title: "Disk temp", icon: "thermometer" }, d?.status ?? "unknown")];
      }
      // One tile per physical disk; drives on the same disk share it.
      const groups = new Map<string, { drives: string[]; celsius: number | null }>();
      for (const drive of d.drives) {
        const id = drive.disk === null ? `drive:${drive.drive}` : `disk:${drive.disk}`;
        const group = groups.get(id) ?? { drives: [], celsius: drive.celsius };
        group.drives.push(drive.drive);
        groups.set(id, group);
      }
      return [...groups.entries()].map(([id, g]) => {
        const base = { key: `disk_temp:${id}`, metric, title: `Disk temp ${g.drives.join(" ")}`, icon: "thermometer" };
        if (g.celsius === null) return missing(base, "unavailable", "Disk doesn't report it");
        return { ...base, status: "ok" as const, value: celsius(g.celsius), detail: g.drives.length > 1 ? `Drives ${g.drives.join(", ")}` : `Drive ${g.drives[0]}`, level: levelFor(metric, g.celsius) };
      });
    }
    case "battery": {
      const b = m.battery;
      const charging = b?.status === "ok" && b.charging;
      const base = { key: "battery", metric, title: "Battery", icon: charging ? "battery-charging" : "battery" };
      if (b?.status !== "ok" || b.percent === undefined) {
        return [missing(base, b?.status ?? "unknown", b?.status === "unsupported" ? "No battery" : undefined)];
      }
      const detail = b.charging ? "⚡ Charging" : b.pluggedIn ? "Plugged in" : "On battery";
      return [{ ...base, status: "ok", value: percent(b.percent), detail, level: b.charging || b.pluggedIn ? "normal" : levelFor(metric, b.percent) }];
    }
    case "wifi": {
      const w = m.wifi;
      const net = m.network;
      const onEthernet = net?.status === "ok" || net?.status === "unknown" ? net.kind === "ethernet" : false;
      const base = { key: "wifi", metric, title: onEthernet ? "Network" : "Wi-Fi", icon: onEthernet ? "ethernet" : "wifi" };
      if (onEthernet) {
        // Say what is really carrying traffic rather than claiming Wi-Fi.
        return [{ ...base, status: "ok", value: "Ethernet", detail: net?.interface ? `${net.interface} · connected` : "Connected", level: null }];
      }
      if (w?.status !== "ok") {
        return [missing(base, w?.status ?? "unknown", w?.status === "unsupported" ? "No Wi-Fi adapter" : undefined)];
      }
      if (!w.connected) return [{ ...base, icon: "wifi-off", status: "ok", value: "Off", detail: "Disconnected", level: "warn" }];
      const parts = [w.ssid, w.signal != null ? `Signal ${w.signal}%` : null].filter(Boolean);
      return [{ ...base, status: "ok", value: "Connected", detail: parts.join(" · ") || "Connected", level: null }];
    }
    case "internet": {
      const base = { key: "internet", metric, title: "Internet", icon: "globe" };
      const i = m.internet;
      if (i?.status !== "ok") return [missing(base, i?.status ?? "unknown")];
      return [i.connected
        ? { ...base, status: "ok", value: "Online", detail: "Reachable", level: null }
        : { ...base, status: "ok", value: "Offline", detail: "No internet access", level: "high" }];
    }
  }
}

function shortGpu(name?: string): string {
  return (name ?? "").replace(/^(NVIDIA|AMD|Intel\(R\))\s+/i, "").replace(/^GeForce\s+/i, "").trim();
}
