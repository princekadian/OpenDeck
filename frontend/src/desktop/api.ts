// Desktop app API: engine endpoints (/api/admin, this PC only) and the pywebview bridge.

export type ServerState = "stopped" | "starting" | "running" | "stopping" | "error";

export interface ServerInfo {
  state: ServerState;
  error: string | null;
  host: string;
  port: number;
  lanOnly: boolean;
  addresses: string[];
  urls: string[];
  startedAt: number | null;
  uptimeSeconds: number | null;
  version: number;
  devices: number;
}

export interface AppSettings {
  serverHost: "0.0.0.0" | "127.0.0.1";
  serverPort: number;
  autoStartServer: boolean;
  minimizeToTray: boolean;
  preferredAddress: string | null;
  logLevel: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  startWithWindows: boolean;
}

export interface NetworkInterface {
  address: string;
  name: string;
  description: string;
  useful: boolean;
}

export interface SettingsView {
  settings: AppSettings;
  startWithWindowsAvailable: boolean;
  interfaces: NetworkInterface[];
  portFromEnvironment: boolean;
}

export interface LogEntry {
  seq: number;
  time: number;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  component: string;
  message: string;
}

export interface Health {
  ok: boolean;
  version: string;
  pid: number;
  uptimeSeconds: number | null;
  database: { ok: boolean; schemaVersion: number };
}

export interface SystemInfo {
  /** System-wide CPU % since the previous call (null on the first). */
  cpu: number | null;
  memory: { total: number; available: number; usage: number };
  processes: Partial<Record<"engine" | "desktop" | "window", { pid: number; workingSet: number; cpuSeconds: number }>>;
}

export interface HostStatus {
  pcName: string;
  port: number;
  urls: string[];
  pairing: { code: string; expiresIn: number };
  connectedDevices: Array<{ sessionId: string; deviceId: string; deviceName: string; remote: string; userAgent: string; connectedAt: number }>;
  pairedDevices: Array<{ id: string; name: string; pairedAt: string; lastSeenAt: string | null; revoked: boolean }>;
}

export class DesktopApiError extends Error {
  constructor(readonly status: number, message: string, readonly fields: Record<string, string> = {}) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/admin${path}`, {
      method,
      signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new DesktopApiError(0, "The engine isn't responding.");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    if (response.status === 422 && Array.isArray(detail)) {
      const fields: Record<string, string> = {};
      for (const issue of detail) fields[String(issue.loc?.at(-1) ?? "form")] = String(issue.msg ?? "Invalid value.").replace(/^Value error, /, "");
      throw new DesktopApiError(422, Object.values(fields)[0] ?? "Check the highlighted fields.", fields);
    }
    throw new DesktopApiError(response.status, detail?.message ?? "Something went wrong.");
  }
  return data as T;
}

export const desktopApi = {
  health: () => request<Health>("GET", "/health"),
  server: () => request<ServerInfo>("GET", "/server"),
  /** Long poll: resolves when the server state changes (or after ~25 s). */
  serverWait: (since: number, signal?: AbortSignal) => request<ServerInfo>("GET", `/server/wait?since=${since}`, undefined, signal),
  serverCommand: (command: "start" | "stop" | "restart") => request<ServerInfo>("POST", `/server/${command}`),
  settings: () => request<SettingsView>("GET", "/app-settings"),
  saveSettings: (settings: AppSettings) => request<SettingsView>("PUT", "/app-settings", settings),
  logs: (after = 0) => request<{ entries: LogEntry[]; last: number }>("GET", `/logs?after=${after}&limit=2000`),
  logFile: (name: "server" | "desktop", lines = 1000) => request<{ path: string; lines: string[] }>("GET", `/logs/file?name=${name}&lines=${lines}`),
  open: (target: "logs" | "data" | "backups" | "remote") => request<void>("POST", "/open", { target }),
  backup: () => request<{ path: string }>("POST", "/backup"),
  system: (hostPid?: number | null, uiPid?: number | null) =>
    request<SystemInfo>("GET", `/system?${hostPid ? `hostPid=${hostPid}&` : ""}${uiPid ? `uiPid=${uiPid}` : ""}`),
  diagnostics: () => request<Record<string, unknown>>("GET", "/diagnostics"),
  status: () => request<HostStatus>("GET", "/status"),
  renameDevice: (id: string, name: string) => request<{ ok: boolean }>("PATCH", `/devices/${encodeURIComponent(id)}`, { name }),
  revokeDevice: (id: string) => request<{ ok: boolean }>("POST", `/devices/${encodeURIComponent(id)}/revoke`),
};

// ---- pywebview bridge (present only inside the desktop window) -------------------------------

export interface HostState {
  engine: "stopped" | "starting" | "running" | "stopping" | "crashed";
  error: string | null;
  url: string | null;
  enginePid: number | null;
  hostPid: number;
  uiPid: number | null;
  version: string;
}

interface Bridge {
  host_state(): Promise<HostState>;
  host_command(command: "restart-engine" | "exit" | "open-logs"): Promise<{ ok: boolean }>;
  take_requested_view(): Promise<string | null>;
  save_text(fileName: string, text: string): Promise<boolean>;
}

declare global {
  interface Window {
    pywebview?: { api: Bridge };
  }
}

/** The desktop bridge, once pywebview has injected it; null in a normal browser. */
export function bridge(): Bridge | null {
  return window.pywebview?.api ?? null;
}

export function whenBridgeReady(callback: () => void): () => void {
  if (window.pywebview?.api) {
    callback();
    return () => {};
  }
  window.addEventListener("pywebviewready", callback, { once: true });
  return () => window.removeEventListener("pywebviewready", callback);
}
