import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DesktopApp } from "./DesktopApp";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

const running = {
  state: "running", error: null, host: "0.0.0.0", port: 8765, lanOnly: true, addresses: ["192.168.1.20"],
  urls: ["http://192.168.1.20:8765"], startedAt: 1, uptimeSeconds: 65, version: 3, devices: 1,
};
const status = {
  pcName: "PC", port: 8765, urls: running.urls, pairing: { code: "123456", expiresIn: 280 },
  connectedDevices: [{ sessionId: "s", deviceId: "d1", deviceName: "Studio iPad", remote: "192.168.1.30", userAgent: "Mozilla/5.0 (iPad; CPU OS 17_0)", connectedAt: 1 }],
  pairedDevices: [{ id: "d1", name: "Studio iPad", pairedAt: "2026-10-01T10:00:00Z", lastSeenAt: null, revoked: false }],
};
const settings = {
  settings: { serverHost: "0.0.0.0", serverPort: 8765, autoStartServer: true, minimizeToTray: true, preferredAddress: null, logLevel: "INFO", startWithWindows: false },
  startWithWindowsAvailable: true,
  interfaces: [{ address: "192.168.1.20", name: "Wi-Fi", description: "", useful: true }, { address: "172.29.0.1", name: "vEthernet", description: "", useful: false }],
  portFromEnvironment: false,
};

type Call = { method: string; url: string; body: unknown };

function mockApi(overrides: Record<string, (body: unknown) => unknown> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });
      const key = `${method} ${url.replace("/api/admin", "").split("?")[0]}`;
      if (overrides[key]) return json(overrides[key](body));
      if (key === "GET /server/wait") return new Promise(() => {}); // long poll: nothing changes
      const fixed: Record<string, unknown> = {
        "GET /server": running,
        "GET /status": status,
        "GET /health": { ok: true, version: "1.0.0", pid: 1, uptimeSeconds: 120, database: { ok: true, schemaVersion: 5 } },
        "GET /system": { cpu: 12, memory: { total: 16e9, available: 8e9, usage: 50 }, processes: { engine: { pid: 1, workingSet: 60e6, cpuSeconds: 1 } } },
        "GET /app-settings": settings,
        "GET /diagnostics": { version: "1.0.0", dataDirectory: "C:\\data", databasePath: "C:\\data\\data.sqlite3", backupDirectory: "C:\\b" },
      };
      return key in fixed ? json(fixed[key]) : new Response(null, { status: 204 });
    }),
  );
  return calls;
}

function json(data: unknown) {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("Desktop app", () => {
  beforeEach(() => {
    window.location.hash = "";
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows server state, the remote address with a local QR code, and connected devices", async () => {
    mockApi();
    render(<DesktopApp />);
    const remote = await screen.findByRole("region", { name: "Connect a phone or tablet" });
    expect(within(remote).getByText("http://192.168.1.20:8765")).toBeInTheDocument();
    expect(within(remote).getByRole("img", { name: "QR code for http://192.168.1.20:8765" })).toBeInTheDocument();
    expect(within(remote).getByText("123456")).toBeInTheDocument();
    const server = screen.getByRole("region", { name: "Remote control server" });
    expect(within(server).getByText("Running")).toBeInTheDocument();
    expect(await screen.findByText("Studio iPad")).toBeInTheDocument();
    expect(screen.getByText(/iPad · 192.168.1.30/)).toBeInTheDocument();
  });

  it("stops the server from the dashboard", async () => {
    const calls = mockApi({ "POST /server/stop": () => ({ ...running, state: "stopped", urls: [], uptimeSeconds: null }) });
    render(<DesktopApp />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop server" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/server/stop"))).toBe(true));
    expect(await screen.findByRole("button", { name: "Start server" })).toBeInTheDocument();
    expect(screen.getByText(/can't connect until you start the server/)).toBeInTheDocument();
  });

  it("saves settings, keeping virtual adapters separate", async () => {
    const calls = mockApi({ "PUT /app-settings": (b) => ({ ...settings, settings: b }) });
    window.location.hash = "#settings";
    render(<DesktopApp />);
    const port = (await screen.findByLabelText("Port")) as HTMLInputElement;
    fireEvent.change(port, { target: { value: "9000" } });
    fireEvent.click(screen.getByLabelText(/Start OpenDeck with Windows/));
    const iface = screen.getByLabelText("Address shown to devices") as HTMLSelectElement;
    expect(within(iface).getByRole("group", { name: /Virtual adapters/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toMatchObject({ serverPort: 9000, startWithWindows: true });
  });

  it("navigates between sections from the rail", async () => {
    mockApi();
    render(<DesktopApp />);
    fireEvent.click(screen.getByRole("link", { name: "Diagnostics" }));
    expect(await screen.findByRole("heading", { name: "Diagnostics" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Diagnostics" })).toHaveAttribute("aria-current", "page");
    await act(async () => {
      fireEvent.click(screen.getByRole("link", { name: "Devices" }));
    });
    expect(await screen.findByRole("heading", { name: "Devices" })).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });
});
