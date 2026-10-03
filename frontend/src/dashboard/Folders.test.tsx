import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeckStore, type HistoryEntry } from "../connection/deckStore";
import { FakeSocket, createFakeSocket, gamingPage, lockButton, page, page2, profile, profile2, welcomeAndSnapshot } from "../test/fakeSocket";
import { Dashboard } from "./Dashboard";

// jsdom has no layout engine; give the grid frame a tablet-landscape size.
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1132 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 648 });

const key = { iconRef: null, actionType: "media_play_pause", appearance: {}, enabled: true };
const audio = { ...key, id: "f1", pageId: "p1", parentId: null, kind: "folder", sortOrder: 1, label: "Audio", actionType: "" };
const volUp = { ...key, id: "v1", pageId: "p1", parentId: "f1", kind: "action", sortOrder: 0, label: "Vol +" };
const advanced = { ...key, id: "f2", pageId: "p1", parentId: "f1", kind: "folder", sortOrder: 1, label: "Advanced", actionType: "" };
const mixer = { ...key, id: "m1", pageId: "p1", parentId: "f2", kind: "action", sortOrder: 0, label: "Mixer" };
const buttons = [lockButton, audio, volUp, advanced, mixer];

/** Records history calls like a browser would, without touching jsdom's real history. */
class FakeHistory {
  entries: unknown[] = [null];
  index = 0;
  get state() {
    return this.entries[this.index];
  }
  pushState(state: unknown) {
    this.entries = [...this.entries.slice(0, this.index + 1), state];
    this.index += 1;
  }
  replaceState(state: unknown) {
    this.entries[this.index] = state;
  }
  back() {
    if (this.index === 0) return;
    this.index -= 1;
    const entry = (this.state as { msd?: HistoryEntry } | null)?.msd;
    window.dispatchEvent(new PopStateEvent("popstate", { state: this.state }));
    return entry;
  }
}

function setup(overrides: Record<string, unknown> = {}) {
  const history = new FakeHistory();
  const store = new DeckStore("t".repeat(43), vi.fn(), { createSocket: createFakeSocket }, history);
  render(<Dashboard token="x" onUnauthorized={vi.fn()} store={store} />);
  const socket = FakeSocket.latest();
  act(() => welcomeAndSnapshot(socket, { buttons, ...overrides }));
  return { socket, store, history };
}

const trail = () => screen.getByRole("navigation", { name: "Location" });
const backKey = () => document.querySelector<HTMLButtonElement>(".deck-key--back")!;

describe("Folders on the dashboard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    localStorage.clear();
  });
  afterEach(() => vi.useRealTimers());

  it("opens a folder locally, shows a generated Back key, and returns", () => {
    const { socket } = setup();
    expect(screen.queryByRole("button", { name: "Vol +" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Audio, folder" }));

    expect(screen.getByRole("button", { name: "Vol +" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lock" })).not.toBeInTheDocument();
    expect(within(trail()).getByRole("heading", { name: "Audio" })).toHaveAttribute("aria-current", "location");
    // Pressing a folder never goes to the PC.
    expect(socket.sent.filter((m) => m.type === "ACTION_EXECUTE")).toHaveLength(0);
    // The Back key fills a normal slot, after the folder's own keys.
    const keys = Array.from(document.querySelectorAll(".deck-grid > .deck-key"));
    expect(keys.at(-1)).toBe(backKey());

    fireEvent.click(backKey());
    expect(screen.getByRole("heading", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lock" })).toBeInTheDocument();
    expect(backKey()).toBeNull();
  });

  it("nests folders and jumps back up from the location trail", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Audio, folder" }));
    fireEvent.click(screen.getByRole("button", { name: "Advanced, folder" }));
    expect(screen.getByRole("button", { name: "Mixer" })).toBeInTheDocument();
    expect(within(trail()).getAllByRole("button").map((b) => b.textContent)).toEqual(["Main", "Audio"]);
    fireEvent.click(within(trail()).getByRole("button", { name: "Main" }));
    expect(screen.getByRole("button", { name: "Lock" })).toBeInTheDocument();
  });

  it("stays in a folder across config updates, and leaves it when the folder is deleted", () => {
    const { socket } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Audio, folder" }));
    const renamed = { ...volUp, label: "Louder" };
    act(() => socket.serverSend({ type: "SNAPSHOT", payload: { activeProfileId: "pr", profiles: [profile], pages: [page, page2], buttons: [lockButton, audio, renamed], states: {} } }));
    expect(screen.getByRole("button", { name: "Louder" })).toBeInTheDocument();

    act(() => socket.serverSend({ type: "SNAPSHOT", payload: { activeProfileId: "pr", profiles: [profile], pages: [page, page2], buttons: [lockButton], states: {} } }));
    expect(screen.getByRole("heading", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lock" })).toBeInTheDocument();
  });

  it("resets the folder trail when the page or profile changes", () => {
    setup({ profiles: [profile, profile2], pages: [page, page2, gamingPage] });
    fireEvent.click(screen.getByRole("button", { name: "Audio, folder" }));
    fireEvent.change(screen.getByLabelText("Choose profile"), { target: { value: "pr2" } });
    expect(screen.getByRole("heading", { name: "Games" })).toBeInTheDocument();
    expect(backKey()).toBeNull();
    fireEvent.change(screen.getByLabelText("Choose profile"), { target: { value: "pr" } });
    expect(screen.getByRole("heading", { name: "Main" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Vol +" })).not.toBeInTheDocument();
  });

  it("uses browser history so the browser Back button leaves folders", () => {
    const { history } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Audio, folder" }));
    fireEvent.click(screen.getByRole("button", { name: "Advanced, folder" }));
    expect(history.entries).toHaveLength(3);

    act(() => void history.back()); // browser Back
    expect(within(trail()).getByRole("heading", { name: "Audio" })).toBeInTheDocument();
    fireEvent.click(backKey()); // in-app Back walks the same history
    expect(history.index).toBe(0);
    expect(screen.getByRole("button", { name: "Lock" })).toBeInTheDocument();
  });

  it("keeps navigation per device: two devices sit in different folders", () => {
    const history = new FakeHistory();
    const a = new DeckStore("t".repeat(43), vi.fn(), { createSocket: createFakeSocket }, history);
    const b = new DeckStore("t".repeat(43), vi.fn(), { createSocket: createFakeSocket }, null);
    for (const store of [a, b]) {
      store.start();
      act(() => welcomeAndSnapshot(FakeSocket.latest(), { buttons }));
    }
    a.openFolder("f1");
    a.openFolder("f2");
    expect(a.getSnapshot().folderStack).toEqual(["f1", "f2"]);
    expect(b.getSnapshot().folderStack).toEqual([]);
    b.openFolder("f2"); // not visible from the page: ignored
    expect(b.getSnapshot().folderStack).toEqual([]);
    a.stop();
    b.stop();
  });
});
