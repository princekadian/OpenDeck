import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeckStore } from "../connection/deckStore";
import { FakeSocket, createFakeSocket, lockButton, page, page2, snapshot } from "../test/fakeSocket";
import { Dashboard } from "./Dashboard";
import { formatDuration } from "./DeckKey";

Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1132 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 648 });

function setup(overrides: Record<string, unknown> = {}) {
  const store = new DeckStore("t".repeat(43), vi.fn(), { createSocket: createFakeSocket });
  render(<Dashboard token="x" onUnauthorized={vi.fn()} store={store} />);
  const socket = FakeSocket.latest();
  act(() => {
    socket.serverOpen();
    socket.serverSend({ type: "WELCOME", payload: { serverName: "PC" } });
    socket.serverSend({ type: "SNAPSHOT", payload: snapshot(overrides) });
  });
  return socket;
}

const executes = (socket: FakeSocket) => socket.sent.filter((m) => m.type === "ACTION_EXECUTE");

describe("Control features", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    localStorage.clear();
  });
  afterEach(() => vi.useRealTimers());

  it("asks for a second tap on destructive keys and sends confirmed", () => {
    const shutdown = { ...lockButton, id: "s", label: "Shut down", confirm: true };
    const socket = setup({ buttons: [shutdown] });
    fireEvent.click(screen.getByRole("button", { name: "Shut down" }));
    expect(executes(socket)).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Shut down, Tap again to confirm" })).toHaveAttribute("data-armed");
    fireEvent.click(screen.getByRole("button", { name: "Shut down, Tap again to confirm" }));
    expect(executes(socket)[0].payload).toEqual({ buttonId: "s", confirmed: true });
  });

  it("disarms the confirmation after a few seconds", () => {
    const socket = setup({ buttons: [{ ...lockButton, id: "s", label: "Restart", confirm: true }] });
    fireEvent.click(screen.getByRole("button", { name: "Restart" }));
    act(() => vi.advanceTimersByTime(3_100));
    fireEvent.click(screen.getByRole("button", { name: "Restart" }));
    expect(executes(socket)).toHaveLength(0);
  });

  it("follows NAVIGATE messages and goes back", () => {
    const socket = setup();
    act(() => socket.serverSend({ type: "NAVIGATE", payload: { pageId: page2.id } }));
    expect(screen.getByRole("heading", { name: "Editing" })).toBeInTheDocument();
    act(() => socket.serverSend({ type: "NAVIGATE", payload: { back: true } }));
    expect(screen.getByRole("heading", { name: page.name })).toBeInTheDocument();
  });

  it("animates a timer locally from one state update", () => {
    const socket = setup();
    act(() =>
      socket.serverSend({
        type: "BUTTON_STATE",
        payload: { buttonId: "b1", state: "running:1", detail: { tone: "busy", countdown: { remainingMs: 65_000, running: true } } },
      }),
    );
    expect(screen.getByRole("timer")).toHaveTextContent("1:05");
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByRole("timer")).toHaveTextContent("1:00");
  });

  it("keeps counting down while press feedback is shown", () => {
    const socket = setup();
    act(() =>
      socket.serverSend({
        type: "BUTTON_STATE",
        payload: { buttonId: "b1", state: "running:1", detail: { countdown: { remainingMs: 60_000, running: true } } },
      }),
    );
    act(() => vi.advanceTimersByTime(3_000));
    fireEvent.click(screen.getByRole("button", { name: "Lock" }));
    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.getByRole("timer")).toHaveTextContent("0:55");
  });

  it("shows state text and icon overrides, and clears state", () => {
    const socket = setup();
    act(() => socket.serverSend({ type: "BUTTON_STATE", payload: { buttonId: "b1", state: "muted", detail: { text: "Muted", icon: "volume-off", tone: "error" } } }));
    expect(screen.getByRole("button", { name: "Lock, Muted" })).toHaveAttribute("data-tone", "error");
    act(() => socket.serverSend({ type: "BUTTON_STATE", payload: { buttonId: "b1", state: null, detail: {} } }));
    expect(screen.getByRole("button", { name: "Lock" })).toHaveAttribute("data-tone", "off");
  });

  it("formats durations", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(59_001)).toBe("1:00");
    expect(formatDuration(3_725_000)).toBe("1:02:05");
  });
});
