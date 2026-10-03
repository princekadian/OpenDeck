import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeckStore } from "../connection/deckStore";
import {
  FakeSocket,
  createFakeSocket,
  gamingPage,
  lockButton,
  page,
  profile,
  profile2,
  snapshot,
  welcomeAndSnapshot,
} from "../test/fakeSocket";
import { Dashboard } from "./Dashboard";

function setup() {
  const onUnauthorized = vi.fn();
  const store = new DeckStore("t".repeat(43), onUnauthorized, { createSocket: createFakeSocket });
  render(<Dashboard token="x" onUnauthorized={onUnauthorized} store={store} />);
  const socket = FakeSocket.latest();
  act(() => welcomeAndSnapshot(socket));
  return { socket, onUnauthorized };
}

// jsdom has no layout engine; give the grid frame a tablet-landscape size.
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1132 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 648 });

describe("Dashboard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    localStorage.clear();
  });
  afterEach(() => vi.useRealTimers());

  it("renders header, keys, sockets and pages from the snapshot", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByText("STUDIO-PC")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Connected");
    expect(screen.getByRole("button", { name: "Lock" })).toBeEnabled();
    // One key reflows to a single cell: no empty sockets around it.
    expect(document.querySelectorAll(".deck-socket")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Main" })).toHaveAttribute("aria-current", "page");
  });

  it("shows press feedback immediately, then the server result", () => {
    const { socket } = setup();
    const key = screen.getByRole("button", { name: "Lock" });
    fireEvent.pointerDown(key);
    expect(key).toHaveAttribute("data-held");
    fireEvent.pointerUp(key);
    fireEvent.click(key);

    const request = socket.sent.find((m) => m.type === "ACTION_EXECUTE")!;
    expect(request.payload).toEqual({ buttonId: "b1" });
    expect(screen.getByRole("button", { name: "Lock, Working…" })).toHaveAttribute("aria-busy", "true");

    act(() =>
      socket.serverSend({
        type: "ACTION_RESULT",
        requestId: request.requestId,
        success: true,
        payload: { buttonId: "b1", message: "Windows locked" },
      }),
    );
    expect(screen.getByRole("button", { name: "Lock, Windows locked" })).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1_300));
    expect(screen.getByRole("button", { name: "Lock" })).toBeInTheDocument();
  });

  it("shows the server error message when an action fails", () => {
    const { socket } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Lock" }));
    const request = socket.sent.find((m) => m.type === "ACTION_EXECUTE")!;
    act(() =>
      socket.serverSend({
        type: "ACTION_RESULT",
        requestId: request.requestId,
        success: false,
        error: { code: "platform_error", message: "LockWorkStation failed" },
        payload: { buttonId: "b1" },
      }),
    );
    expect(screen.getByRole("button", { name: "Lock, LockWorkStation failed" })).toHaveAttribute("data-tone", "error");
  });

  it("times out when the PC never answers", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Lock" }));
    act(() => vi.advanceTimersByTime(10_001));
    expect(screen.getByRole("button", { name: "Lock, No response from PC" })).toBeInTheDocument();
  });

  it("switches pages", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Editing" }));
    expect(screen.getByRole("heading", { name: "Editing" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lock" })).not.toBeInTheDocument();
    expect(screen.getByText(/No keys on this page yet/)).toBeInTheDocument();
  });

  it("goes offline, disables keys, and resyncs on reconnect", () => {
    const { socket } = setup();
    act(() => socket.serverClose(1006));
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach the PC.");
    expect(screen.getByRole("status")).toHaveTextContent("PC offline");
    expect(screen.getByRole("button", { name: "Lock" })).toBeDisabled();

    act(() => vi.advanceTimersByTime(500));
    act(() => welcomeAndSnapshot(FakeSocket.latest()));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lock" })).toBeEnabled();
  });

  it("fails an in-flight press when the connection drops", () => {
    const { socket } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Lock" }));
    act(() => socket.serverClose(1006));
    expect(screen.getByRole("button", { name: "Lock, Connection lost" })).toBeInTheDocument();
  });

  it("reports unauthorized when the device is revoked", () => {
    const { socket, onUnauthorized } = setup();
    act(() => socket.serverClose(4004));
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("applies live BUTTON_STATE updates", () => {
    const { socket } = setup();
    act(() => socket.serverSend({ type: "BUTTON_STATE", payload: { buttonId: "b1", state: "active", detail: { text: "Running", tone: "online" } } }));
    expect(screen.getByRole("button", { name: "Lock, Running" })).toHaveAttribute("data-tone", "online");
  });
});

describe("Dashboard reflow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    localStorage.clear();
  });
  afterEach(() => vi.useRealTimers());

  it("renders keys in logical order regardless of stored grid gaps", () => {
    const onUnauthorized = vi.fn();
    const store = new DeckStore("t".repeat(43), onUnauthorized, { createSocket: createFakeSocket });
    render(<Dashboard token="x" onUnauthorized={onUnauthorized} store={store} />);
    const socket = FakeSocket.latest();
    const key = (id: string, sortOrder: number) => ({ ...lockButton, id, label: id, sortOrder });
    act(() => {
      socket.serverOpen();
      socket.serverSend({ type: "WELCOME", payload: { serverName: "PC" } });
      socket.serverSend({
        type: "SNAPSHOT",
        payload: snapshot({ pages: [page], buttons: [key("C", 2), key("A", 0), key("B", 1)] }),
      });
    });
    const labels = Array.from(document.querySelectorAll(".deck-key__label"), (el) => el.textContent);
    expect(labels).toEqual(["A", "B", "C"]);
    const grid = document.querySelector<HTMLElement>(".deck-grid")!;
    expect(grid.style.getPropertyValue("--cols")).toBe("3");
  });
});

describe("PageBar on narrow screens", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    localStorage.clear();
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 180 });
  });
  afterEach(() => {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1132 });
    vi.useRealTimers();
  });

  it("switches to a previous/next stepper when tabs do not fit", () => {
    setup();
    expect(screen.queryByRole("button", { name: "Editing" })).not.toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByRole("heading", { name: "Editing" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Choose page" }), { target: { value: "p1" } });
    expect(screen.getByRole("heading", { name: "Main" })).toBeInTheDocument();
  });
});

describe("Profiles and live configuration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    localStorage.clear();
  });
  afterEach(() => vi.useRealTimers());

  const twoProfiles = () =>
    snapshot({ profiles: [profile, profile2], pages: [page, gamingPage], buttons: [lockButton] });

  it("switches profile and shows that profile's pages", () => {
    const { socket } = setup();
    act(() => socket.serverSend({ type: "SNAPSHOT", payload: twoProfiles() }));
    fireEvent.change(screen.getByRole("combobox", { name: "Choose profile" }), { target: { value: "pr2" } });
    expect(screen.getByRole("heading", { name: "Games" })).toBeInTheDocument();
    expect(screen.getByText(/No keys on this page yet/)).toBeInTheDocument();
  });

  it("applies a live configuration update without reconnecting", () => {
    const { socket } = setup();
    const youtube = { ...lockButton, id: "b2", label: "YouTube", sortOrder: 1, actionType: "open_url", iconRef: null };
    act(() => socket.serverSend({ type: "SNAPSHOT", payload: snapshot({ buttons: [lockButton, youtube] }) }));
    expect(screen.getByRole("button", { name: "YouTube" })).toBeInTheDocument();
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("follows the PC when it changes the active profile", () => {
    const { socket } = setup();
    act(() => socket.serverSend({ type: "SNAPSHOT", payload: twoProfiles() }));
    act(() => socket.serverSend({ type: "SNAPSHOT", payload: { ...twoProfiles(), activeProfileId: "pr2" } }));
    expect(screen.getByRole("heading", { name: "Games" })).toBeInTheDocument();
  });

  it("keeps the device's own profile choice across reconnects", () => {
    const { socket } = setup();
    act(() => socket.serverSend({ type: "SNAPSHOT", payload: twoProfiles() }));
    fireEvent.change(screen.getByRole("combobox", { name: "Choose profile" }), { target: { value: "pr2" } });
    act(() => socket.serverClose(1006));
    act(() => vi.advanceTimersByTime(600));
    act(() => welcomeAndSnapshot(FakeSocket.latest(), twoProfiles()));
    expect(screen.getByRole("heading", { name: "Games" })).toBeInTheDocument();
  });

  it("shows disabled keys as disabled and does not send presses", () => {
    const { socket } = setup();
    act(() => socket.serverSend({ type: "SNAPSHOT", payload: snapshot({ buttons: [{ ...lockButton, enabled: false }] }) }));
    const key = screen.getByRole("button", { name: "Lock, Disabled" });
    expect(key).toBeDisabled();
    fireEvent.click(key);
    expect(socket.sent.some((m) => m.type === "ACTION_EXECUTE")).toBe(false);
  });

  it("renders uploaded icons as images", () => {
    const { socket } = setup();
    const ref = "asset:" + "a".repeat(64) + ".png";
    act(() => socket.serverSend({ type: "SNAPSHOT", payload: snapshot({ buttons: [{ ...lockButton, iconRef: ref }] }) }));
    const img = document.querySelector<HTMLImageElement>(".deck-key__icon")!;
    expect(img.tagName).toBe("IMG");
    expect(img.getAttribute("src")).toBe(`/api/assets/${"a".repeat(64)}.png`);
  });
});
