// Wire protocol v2. Mirrors backend/opendeck/protocol.py — see docs/PROTOCOL.md.

export const PROTOCOL_VERSION = 2;

export type ClientMessageType = "HELLO" | "ACTION_EXECUTE" | "MONITOR_SUBSCRIBE" | "PING";
export type ServerMessageType =
  | "WELCOME"
  | "SNAPSHOT"
  | "ACTION_RESULT"
  | "BUTTON_STATE"
  | "NAVIGATE"
  | "CONFIG_CHANGED"
  | "DEVICE_CONNECTED"
  | "DEVICE_DISCONNECTED"
  | "SYSTEM_MONITOR"
  | "PONG"
  | "ERROR";

export interface ErrorInfo {
  code: string;
  message: string;
}

export interface Envelope<T extends string = string, P = Record<string, unknown>> {
  version: number;
  type: T;
  requestId?: string;
  success?: boolean;
  error?: ErrorInfo;
  payload: P;
}

export const CloseCode = {
  AUTH_REQUIRED: 4001,
  UNSUPPORTED_VERSION: 4002,
  AUTH_FAILED: 4003,
  DEVICE_REVOKED: 4004,
} as const;

export interface Profile {
  id: string;
  name: string;
  iconRef: string | null;
  sortOrder: number;
}

export interface Page {
  id: string;
  profileId: string;
  name: string;
  iconRef: string | null;
  sortOrder: number;
  /** "monitor" pages show live System Monitoring instead of keys. Absent = "deck". */
  kind?: "deck" | "monitor";
}

/** A key as the control surface sees it. Action settings never leave the PC. */
export interface DeckButton {
  id: string;
  pageId: string;
  /** Folder this key is inside; null = directly on the page. */
  parentId?: string | null;
  /** "folder" keys open their contents on the device; they never run anything on the PC. */
  kind?: "action" | "folder";
  sortOrder: number;
  label: string;
  iconRef: string | null;
  actionType: string;
  appearance: Record<string, unknown>;
  enabled: boolean;
  /** Needs a second tap before running (Shut down, Restart…). */
  confirm?: boolean;
}

/** Generic display vocabulary shared by every stateful action (see backend services/state.py). */
export interface StateDetail {
  text?: string;
  icon?: string;
  tone?: "online" | "busy" | "error";
  /** endsAt is added on the device (local clock) when the state arrives. */
  countdown?: { remainingMs: number; running: boolean; endsAt?: number };
  [key: string]: unknown;
}

export interface ButtonState {
  state: string;
  detail: StateDetail;
}

export interface WelcomePayload {
  deviceId: string;
  deviceName: string;
  serverName: string;
  protocolVersion: number;
}

export interface SnapshotPayload {
  activeProfileId: string | null;
  profiles: Profile[];
  pages: Page[];
  buttons: DeckButton[];
  states: Record<string, ButtonState>;
}

export interface ActionResultPayload {
  buttonId: string;
  message?: string;
  data?: Record<string, unknown>;
}

export interface ButtonStatePayload {
  buttonId: string;
  /** null clears the state (e.g. the button was changed to a stateless action). */
  state: string | null;
  detail: StateDetail;
}

export interface NavigatePayload {
  pageId?: string;
  profileId?: string;
  back?: boolean;
}

/** Every metric says whether it has a value. Missing data is never replaced by a guess. */
export type MetricStatus = "ok" | "unavailable" | "unsupported" | "error" | "unknown";

export interface MonitorDrive {
  drive: string;
  usage: number;
  used: number;
  total: number;
  free: number;
  /** Physical disk number; drives on one disk share its temperature. */
  disk: number | null;
  celsius: number | null;
}

/** Readings from the PC. All byte values are bytes; speeds are bytes per second. */
export interface MonitorMetrics {
  cpu?: { status: MetricStatus; usage?: number };
  gpu?: { status: MetricStatus; usage?: number; name?: string; adapters?: Array<{ id: string; name: string; usage: number }> };
  memory?: { status: MetricStatus; usage?: number; used?: number; total?: number; available?: number };
  cpuTemp?: { status: MetricStatus; celsius?: number; source?: string };
  gpuTemp?: { status: MetricStatus; celsius?: number; name?: string };
  network?: {
    status: MetricStatus;
    interface?: string;
    kind?: "wifi" | "ethernet";
    connected?: boolean;
    linkBps?: number;
    upBytesPerSec?: number;
    downBytesPerSec?: number;
  };
  disks?: { status: MetricStatus; drives?: MonitorDrive[] };
  battery?: { status: MetricStatus; percent?: number; charging?: boolean; pluggedIn?: boolean | null };
  wifi?: { status: MetricStatus; connected?: boolean; ssid?: string | null; signal?: number | null; rxKbps?: number | null };
  internet?: { status: MetricStatus; connected?: boolean };
}

export type MonitorMetricId =
  | "cpu" | "gpu" | "ram" | "cpu_temp" | "gpu_temp" | "net_up" | "net_down"
  | "disk" | "disk_temp" | "battery" | "wifi" | "internet";

export interface SystemMonitorPayload {
  /** PC clock, ms since epoch. */
  timestamp: number;
  intervalMs: number;
  /** Tiles to show, in order. */
  tiles: MonitorMetricId[];
  metrics: MonitorMetrics;
}

export type ServerMessage =
  | Envelope<"WELCOME", WelcomePayload>
  | Envelope<"SNAPSHOT", SnapshotPayload>
  | Envelope<"ACTION_RESULT", ActionResultPayload>
  | Envelope<"BUTTON_STATE", ButtonStatePayload>
  | Envelope<"NAVIGATE", NavigatePayload>
  | Envelope<"SYSTEM_MONITOR", SystemMonitorPayload>
  | Envelope<"CONFIG_CHANGED" | "DEVICE_CONNECTED" | "DEVICE_DISCONNECTED" | "PONG" | "ERROR">;

export function clientMessage(
  type: ClientMessageType,
  payload: Record<string, unknown> = {},
  requestId?: string,
): Envelope<ClientMessageType> {
  return { version: PROTOCOL_VERSION, type, payload, ...(requestId ? { requestId } : {}) };
}

/** crypto.randomUUID needs a secure context; LAN http is not one, so build v4 manually. */
export function newRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
