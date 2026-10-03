import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ActionFields } from "./actionForm/ActionFields";
import { clearChoiceCache } from "./actionForm/choices";
import type { ActionInfo, EditorTree, ObsInfo } from "./api";
import { ObsPanel } from "./ObsPanel";

const connected: ObsInfo = {
  status: "connected",
  message: "Connected to OBS 32.1.2",
  version: "32.1.2",
  settings: { enabled: true, host: "127.0.0.1", port: 4455, hasPassword: true },
};

function mock(routes: Record<string, (body: unknown) => unknown>) {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });
      const key = `${method} ${url.replace("/api/admin", "")}`;
      const handler = routes[key];
      if (!handler) return new Response(JSON.stringify({ detail: { code: "OBS_NOT_CONNECTED", message: "OBS is not connected. Is OBS running?" } }), { status: 409 });
      return new Response(JSON.stringify(handler(body)), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

const tree = { categories: [], actions: [], keys: [], profiles: [], pages: [], buttons: [], activeProfileId: null } as unknown as EditorTree;

const sourceAction: ActionInfo = {
  type: "obs_toggle_source",
  displayName: "OBS: Toggle source",
  description: "",
  category: "streaming",
  icon: "window",
  status: "available",
  trustedOnly: false,
  destructive: false,
  stateful: true,
  configSchema: {
    type: "object",
    properties: {
      scene: { type: "string", title: "Scene", default: "", widget: "obs-scene" },
      source: { type: "string", title: "Source", widget: "obs-source", sceneField: "scene", sourceKind: "all" } as never,
    },
    required: ["source"],
  },
};

describe("OBS in the editor", () => {
  beforeEach(() => clearChoiceCache());
  afterEach(() => vi.unstubAllGlobals());

  it("shows the connection status and keeps the saved password when the field is empty", async () => {
    const calls = mock({ "GET /obs": () => connected, "PUT /obs": () => connected });
    render(<ObsPanel />);
    expect(await screen.findByRole("status")).toHaveTextContent("Connected");
    expect(await screen.findByLabelText("Server password")).toHaveAttribute("placeholder", "Saved. Type to replace it");
    fireEvent.change(screen.getByLabelText("Port"), { target: { value: "4466" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and connect" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ enabled: true, host: "127.0.0.1", port: 4466, password: null });
  });

  it("lists scenes and the sources of the chosen scene", async () => {
    mock({
      "GET /obs": () => connected,
      "GET /obs/scenes": () => ({ items: ["Starting", "Gameplay", "BRB"] }),
      "GET /obs/sources?scene=": () => ({ items: ["Webcam", "Overlay"] }),
      "GET /obs/sources?scene=BRB": () => ({ items: ["Webcam", "BRB card"] }),
    });
    const onChange = vi.fn();
    const { rerender } = render(<ActionFields tree={tree} action={sourceAction} config={{ scene: "" }} errors={{}} onChange={onChange} />);
    expect(await screen.findByRole("option", { name: "Gameplay" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Overlay" })).toBeInTheDocument();
    rerender(<ActionFields tree={tree} action={sourceAction} config={{ scene: "BRB" }} errors={{}} onChange={onChange} />);
    expect(await screen.findByRole("option", { name: "BRB card" })).toBeInTheDocument();
  });

  it("lets names be typed while OBS is offline", async () => {
    mock({ "GET /obs": () => ({ ...connected, status: "unreachable", message: "Can't reach OBS." }) });
    const onChange = vi.fn();
    render(<ActionFields tree={tree} action={sourceAction} config={{ scene: "" }} errors={{}} onChange={onChange} />);
    expect(await screen.findByText("OBS: Can't reach OBS.")).toBeInTheDocument();
    const inputs = await screen.findAllByPlaceholderText("Type the exact name used in OBS");
    fireEvent.change(inputs[1], { target: { value: "Webcam" } });
    expect(onChange).toHaveBeenCalledWith({ scene: "", source: "Webcam" });
  });
});
