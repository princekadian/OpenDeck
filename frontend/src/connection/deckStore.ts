// Dashboard state store, consumed through useSyncExternalStore.

import { useSyncExternalStore } from "react";
import type {
  ButtonState,
  DeckButton,
  Page,
  Profile,
  ServerMessage,
  SnapshotPayload,
  SystemMonitorPayload,
} from "../protocol/messages";
import { connectionTraceEnabled, reportTrace } from "../diagnostics/errorReporting";
import { DeckClient, defaultSocketUrl, type ConnectionStatus, type DeckClientOptions } from "./DeckClient";
import { loadView, saveView, type ViewMemory } from "./viewMemory";

export type PressPhase = "pending" | "success" | "error" | "armed";

export interface PressFeedback {
  phase: PressPhase;
  message?: string;
}

/** Latest System Monitoring reading on this device, with short histories for sparklines. */
export interface MonitorView {
  payload: SystemMonitorPayload;
  /** Device clock when it arrived (the PC clock may differ). */
  receivedAt: number;
  history: Record<string, number[]>;
}

export const MONITOR_HISTORY = 40;

export interface DeckState {
  status: ConnectionStatus;
  retryInMs?: number;
  serverName: string | null;
  profiles: Profile[];
  /** Profile the PC marks as active; devices follow it when it changes. */
  serverActiveProfileId: string | null;
  /** Profile this device is showing. */
  activeProfileId: string | null;
  pages: Page[];
  buttons: DeckButton[];
  states: Record<string, ButtonState>;
  activePageId: string | null;
  /** Folders opened on this device, outermost first. Empty = the page itself. */
  folderStack: string[];
  feedback: Record<string, PressFeedback>;
  synced: boolean;
  monitor: MonitorView | null;
}

const RESULT_TIMEOUT_MS = 10_000;
const FEEDBACK_VISIBLE_MS = { success: 1_200, error: 4_000, armed: 3_000 } as const;
const HISTORY_LIMIT = 20;

export function initialDeckState(): DeckState {
  return {
    status: "connecting",
    serverName: null,
    profiles: [],
    serverActiveProfileId: null,
    activeProfileId: null,
    pages: [],
    buttons: [],
    states: {},
    activePageId: null,
    folderStack: [],
    feedback: {},
    synced: false,
    monitor: null,
  };
}

export class DeckStore {
  private state: DeckState = initialDeckState();
  private readonly listeners = new Set<() => void>();
  private readonly client: DeckClient;
  private readonly pending = new Map<string, { buttonId: string; timer: ReturnType<typeof setTimeout> }>();
  private readonly feedbackTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private view: ViewMemory = loadView();
  /** A monitoring page is on screen: the PC should stream readings to this device. */
  private monitorWanted = false;
  /** Pages shown before the current one, for the "Go back" action. */
  private pageHistory: string[] = [];

  constructor(
    token: string,
    private readonly onUnauthorized: () => void,
    clientOverrides: Partial<DeckClientOptions> = {},
    /** Browser history, so the browser's Back button leaves folders. Optional. */
    private readonly history: Pick<History, "pushState" | "replaceState" | "back" | "state"> | null =
      typeof window !== "undefined" ? window.history : null,
  ) {
    this.client = new DeckClient({
      url: defaultSocketUrl(),
      token,
      listener: {
        onStatus: (status, detail) => this.handleStatus(status, detail?.retryInMs),
        onMessage: (message) => this.handleMessage(message),
        onTrace: connectionTraceEnabled() ? reportTrace : undefined,
      },
      ...clientOverrides,
    });
  }

  // ---- store protocol ----------------------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): DeckState => this.state;

  start(): void {
    this.client.start();
  }

  stop(): void {
    this.client.stop();
    for (const { timer } of this.pending.values()) clearTimeout(timer);
    for (const timer of this.feedbackTimers.values()) clearTimeout(timer);
    this.pending.clear();
    this.feedbackTimers.clear();
  }

  nudge(): void {
    this.client.nudge();
  }

  // ---- commands ----------------------------------------------------------

  selectPage(pageId: string, { record = true } = {}): void {
    const page = this.state.pages.find((p) => p.id === pageId);
    if (!page) return;
    if (pageId === this.state.activePageId) {
      if (this.state.folderStack.length) this.setFolders([], "replace"); // tapping the page tab leaves folders
      return;
    }
    if (record) this.pushHistory();
    this.update({ activePageId: pageId, activeProfileId: page.profileId, folderStack: [] });
    this.syncHistory("replace");
    this.remember();
  }

  // ---- folders (navigation is local to this device) -----------------------------------

  openFolder(folderId: string): void {
    const folder = this.state.buttons.find((b) => b.id === folderId && b.kind === "folder");
    if (!folder || folder.pageId !== this.state.activePageId) return;
    if ((folder.parentId ?? null) !== (this.state.folderStack.at(-1) ?? null)) return; // must be visible here
    this.setFolders([...this.state.folderStack, folderId], "push");
  }

  /** The Back key: leave the current folder. Uses browser history when it owns the entry. */
  closeFolder(): void {
    const stack = this.state.folderStack;
    if (!stack.length) return;
    const entry = (this.history?.state as { msd?: HistoryEntry } | null)?.msd;
    if (entry && entry.pageId === this.state.activePageId && sameStack(entry.stack, stack)) {
      this.history!.back(); // popstate restores the parent folder
      return;
    }
    this.setFolders(stack.slice(0, -1), "replace");
  }

  /** Jump to a folder level from the header trail (0 = page). */
  goToFolderLevel(depth: number): void {
    if (depth < this.state.folderStack.length) this.setFolders(this.state.folderStack.slice(0, depth), "replace");
  }

  /** Browser back/forward landed on one of our entries. */
  restoreFromHistory(entry: HistoryEntry | null | undefined): void {
    if (!entry || entry.pageId !== this.state.activePageId) {
      if (this.state.folderStack.length) this.update({ folderStack: [] });
      return;
    }
    this.update({ folderStack: validStack(entry.stack, this.state.buttons, entry.pageId) });
  }

  private setFolders(stack: string[], mode: "push" | "replace"): void {
    this.update({ folderStack: stack });
    this.syncHistory(mode);
  }

  private syncHistory(mode: "push" | "replace"): void {
    if (!this.history) return;
    const entry: HistoryEntry = { pageId: this.state.activePageId, stack: this.state.folderStack };
    try {
      const state = { ...(this.history.state ?? {}), msd: entry };
      if (mode === "push") this.history.pushState(state, "");
      else this.history.replaceState(state, "");
    } catch {
      /* history unavailable (sandboxed frame): folder navigation still works in-app */
    }
  }

  selectProfile(profileId: string): void {
    if (!this.state.profiles.some((p) => p.id === profileId) || profileId === this.state.activeProfileId) return;
    this.pushHistory();
    const pageId = pickPage(this.state.pages, profileId, this.view.pages[profileId]);
    this.update({ activeProfileId: profileId, activePageId: pageId, folderStack: [] });
    this.syncHistory("replace");
    this.remember();
  }

  goBack(): boolean {
    if (this.state.folderStack.length) {
      this.closeFolder();
      return true;
    }
    while (this.pageHistory.length) {
      const pageId = this.pageHistory.pop()!;
      if (this.state.pages.some((p) => p.id === pageId)) {
        this.selectPage(pageId, { record: false });
        return true;
      }
    }
    return false;
  }

  private pushHistory(): void {
    const current = this.state.activePageId;
    if (current && this.pageHistory.at(-1) !== current) this.pageHistory = [...this.pageHistory, current].slice(-HISTORY_LIMIT);
  }

  private remember(): void {
    const { activeProfileId, activePageId } = this.state;
    if (!activeProfileId) return;
    this.view = {
      profileId: activeProfileId,
      pages: activePageId ? { ...this.view.pages, [activeProfileId]: activePageId } : this.view.pages,
    };
    saveView(this.view);
  }

  /** Start or stop receiving System Monitoring readings (only while a monitoring page is visible). */
  watchMonitor(active: boolean): void {
    if (active === this.monitorWanted) return;
    this.monitorWanted = active;
    this.client.setMonitoring(active); // if offline, WELCOME re-sends it
  }

  press(buttonId: string): void {
    const current = this.state.feedback[buttonId]?.phase;
    if (current === "pending") return; // ignore double taps
    const button = this.state.buttons.find((b) => b.id === buttonId);
    // Destructive keys need a second tap within a few seconds.
    if (button?.confirm && current !== "armed") {
      this.setFeedback(buttonId, { phase: "armed", message: "Tap again to confirm" });
      return;
    }
    const requestId = this.client.executeButton(buttonId, current === "armed");
    if (!requestId) {
      this.setFeedback(buttonId, { phase: "error", message: "PC offline" });
      return;
    }
    const timer = setTimeout(() => {
      this.pending.delete(requestId);
      this.setFeedback(buttonId, { phase: "error", message: "No response from PC" });
    }, RESULT_TIMEOUT_MS);
    this.pending.set(requestId, { buttonId, timer });
    this.setFeedback(buttonId, { phase: "pending" });
  }

  // ---- event handling ----------------------------------------------------

  private handleStatus(status: ConnectionStatus, retryInMs?: number): void {
    if (status === "unauthorized") {
      this.update({ status });
      this.onUnauthorized();
      return;
    }
    if (status === "offline") this.failPending("Connection lost");
    this.update({ status, retryInMs });
  }

  private handleMessage(message: ServerMessage): void {
    switch (message.type) {
      case "WELCOME":
        this.update({ serverName: message.payload.serverName });
        // The PC forgets subscriptions when a connection ends.
        if (this.monitorWanted) this.client.setMonitoring(true);
        break;
      case "SYSTEM_MONITOR":
        this.update({ monitor: nextMonitor(this.state.monitor, message.payload) });
        break;
      case "SNAPSHOT": {
        const payload = message.payload;
        const { activeProfileId, activePageId } = resolveSelection(payload, this.state, this.view);
        // Keep the device inside its folders if they still exist on the same page.
        const keepFolders = activePageId === this.state.activePageId;
        let folderStack = keepFolders ? validStack(this.state.folderStack, payload.buttons, activePageId) : [];
        if (!this.state.synced) {
          // First snapshot after a reload: restore the folder trail kept in browser history.
          const entry = (this.history?.state as { msd?: HistoryEntry } | null)?.msd;
          if (entry?.pageId === activePageId) folderStack = validStack(entry.stack, payload.buttons, activePageId);
        }
        this.update({
          profiles: payload.profiles,
          pages: payload.pages,
          buttons: payload.buttons,
          states: Object.fromEntries(Object.entries(payload.states).map(([id, s]) => [id, anchorCountdown(s)])),
          serverActiveProfileId: payload.activeProfileId,
          activeProfileId,
          activePageId,
          folderStack,
          synced: true,
        });
        this.remember();
        break;
      }
      case "BUTTON_STATE": {
        const { buttonId, state, detail } = message.payload;
        const { [buttonId]: _old, ...others } = this.state.states;
        this.update({ states: state === null ? others : { ...others, [buttonId]: anchorCountdown({ state, detail: detail ?? {} }) } });
        break;
      }
      case "NAVIGATE": {
        const { pageId, profileId, back } = message.payload;
        if (back) this.goBack();
        else if (pageId) this.selectPage(pageId);
        else if (profileId) this.selectProfile(profileId);
        break;
      }
      case "ACTION_RESULT": {
        const entry = message.requestId ? this.pending.get(message.requestId) : undefined;
        if (!entry || !message.requestId) return;
        clearTimeout(entry.timer);
        this.pending.delete(message.requestId);
        this.setFeedback(
          entry.buttonId,
          message.success
            ? { phase: "success", message: message.payload.message }
            : { phase: "error", message: message.error?.message ?? "Action failed" },
        );
        break;
      }
      default:
        break;
    }
  }

  private failPending(reason: string): void {
    for (const [requestId, { buttonId, timer }] of this.pending) {
      clearTimeout(timer);
      this.pending.delete(requestId);
      this.setFeedback(buttonId, { phase: "error", message: reason });
    }
  }

  private setFeedback(buttonId: string, feedback: PressFeedback): void {
    const existing = this.feedbackTimers.get(buttonId);
    if (existing) clearTimeout(existing);
    this.feedbackTimers.delete(buttonId);
    this.update({ feedback: { ...this.state.feedback, [buttonId]: feedback } });
    if (feedback.phase === "pending") return;
    this.feedbackTimers.set(
      buttonId,
      setTimeout(() => {
        this.feedbackTimers.delete(buttonId);
        const { [buttonId]: _cleared, ...rest } = this.state.feedback;
        this.update({ feedback: rest });
      }, FEEDBACK_VISIBLE_MS[feedback.phase]),
    );
  }

  private update(patch: Partial<DeckState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
}

export function useDeck(store: DeckStore): DeckState {
  return useSyncExternalStore(store.subscribe, store.getSnapshot);
}

function pickPage(pages: Page[], profileId: string, preferred?: string): string | null {
  const own = pages.filter((p) => p.profileId === profileId);
  return (own.find((p) => p.id === preferred) ?? own[0])?.id ?? null;
}

/**
 * Which profile/page to show after a snapshot. Keeps the device where it was when
 * possible (also across reloads), but follows the PC when it switches the active profile.
 */
export function resolveSelection(
  snapshot: SnapshotPayload,
  current: Pick<DeckState, "activeProfileId" | "activePageId" | "serverActiveProfileId" | "synced">,
  memory: ViewMemory,
): { activeProfileId: string | null; activePageId: string | null } {
  const exists = (id: string | null | undefined): id is string =>
    !!id && snapshot.profiles.some((p) => p.id === id);
  const serverSwitched =
    current.synced && snapshot.activeProfileId !== current.serverActiveProfileId && exists(snapshot.activeProfileId);

  let profileId: string | null;
  if (serverSwitched) profileId = snapshot.activeProfileId;
  else if (exists(current.activeProfileId)) profileId = current.activeProfileId;
  else if (exists(memory.profileId)) profileId = memory.profileId;
  else if (exists(snapshot.activeProfileId)) profileId = snapshot.activeProfileId;
  else profileId = snapshot.profiles[0]?.id ?? null;

  if (!profileId) return { activeProfileId: null, activePageId: null };
  const keep = snapshot.pages.some((p) => p.id === current.activePageId && p.profileId === profileId);
  const pageId = keep ? current.activePageId : pickPage(snapshot.pages, profileId, memory.pages[profileId]);
  return { activeProfileId: profileId, activePageId: pageId };
}

/** Pin a running countdown to this device's clock at arrival, so re-renders never restart it. */
function anchorCountdown(state: ButtonState): ButtonState {
  const countdown = state.detail?.countdown;
  if (!countdown?.running) return state;
  return { ...state, detail: { ...state.detail, countdown: { ...countdown, endsAt: Date.now() + countdown.remainingMs } } };
}

/** Values kept for sparklines, keyed like tiles. */
function samples(payload: SystemMonitorPayload): Record<string, number | undefined> {
  const m = payload.metrics;
  return {
    cpu: m.cpu?.status === "ok" ? m.cpu.usage : undefined,
    gpu: m.gpu?.status === "ok" ? m.gpu.usage : undefined,
    ram: m.memory?.status === "ok" ? m.memory.usage : undefined,
    net_up: m.network?.status === "ok" ? m.network.upBytesPerSec : undefined,
    net_down: m.network?.status === "ok" ? m.network.downBytesPerSec : undefined,
  };
}

export function nextMonitor(previous: MonitorView | null, payload: SystemMonitorPayload, now = Date.now()): MonitorView {
  const history: Record<string, number[]> = { ...(previous?.history ?? {}) };
  // A keep-alive repeats the last reading; don't stretch the sparkline with it.
  const repeat = previous && previous.payload.timestamp === payload.timestamp;
  if (!repeat) {
    for (const [key, value] of Object.entries(samples(payload))) {
      if (value === undefined) continue;
      history[key] = [...(history[key] ?? []), value].slice(-MONITOR_HISTORY);
    }
  }
  return { payload, receivedAt: now, history };
}

export interface HistoryEntry {
  pageId: string | null;
  stack: string[];
}

function sameStack(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

/** Longest prefix of `stack` that is still a chain of folders on `pageId`. */
export function validStack(stack: string[], buttons: DeckButton[], pageId: string | null): string[] {
  const valid: string[] = [];
  let parent: string | null = null;
  for (const id of stack) {
    const folder = buttons.find((b) => b.id === id);
    if (!folder || folder.kind !== "folder" || folder.pageId !== pageId || (folder.parentId ?? null) !== parent) break;
    valid.push(id);
    parent = id;
  }
  return valid;
}
