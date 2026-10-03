// Minimal in-memory WebSocket double for client/store tests.

export class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState: number = WebSocket.CONNECTING;
  sent: Array<Record<string, any>> = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }

  static latest(): FakeSocket {
    return FakeSocket.instances[FakeSocket.instances.length - 1];
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(code = 1000): void {
    if (this.readyState === WebSocket.CLOSED) return;
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code });
  }

  // ---- test helpers ----
  serverOpen(): void {
    this.readyState = WebSocket.OPEN;
    this.onopen?.();
  }

  serverSend(message: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify({ version: 1, payload: {}, ...message }) });
  }

  serverClose(code = 1006): void {
    this.close(code);
  }
}

export const createFakeSocket = (url: string) => new FakeSocket(url) as unknown as WebSocket;

export const profile = { id: "pr", name: "Main", iconRef: null, sortOrder: 0 };
export const profile2 = { id: "pr2", name: "Gaming", iconRef: null, sortOrder: 1 };
export const page = { id: "p1", profileId: "pr", name: "Main", iconRef: null, sortOrder: 0 };
export const page2 = { id: "p2", profileId: "pr", name: "Editing", iconRef: null, sortOrder: 1 };
export const gamingPage = { id: "g1", profileId: "pr2", name: "Games", iconRef: null, sortOrder: 0 };
export const lockButton = {
  id: "b1",
  pageId: "p1",
  sortOrder: 0,
  label: "Lock",
  iconRef: "builtin:lock",
  actionType: "lock_windows",
  appearance: {},
  enabled: true,
};

export function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    activeProfileId: "pr",
    profiles: [profile],
    pages: [page, page2],
    buttons: [lockButton],
    states: {},
    ...overrides,
  };
}

export function welcomeAndSnapshot(socket: FakeSocket, overrides: Record<string, unknown> = {}): void {
  socket.serverOpen();
  socket.serverSend({ type: "WELCOME", payload: { deviceId: "d", deviceName: "iPad", serverName: "STUDIO-PC", protocolVersion: 2 } });
  socket.serverSend({ type: "SNAPSHOT", payload: snapshot(overrides) });
}
