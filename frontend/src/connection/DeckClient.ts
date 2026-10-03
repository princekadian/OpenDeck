// WebSocket transport: handshake, heartbeat, exponential-backoff reconnect.
// Holds no UI state itself; it reports events to a listener (the store).

import {
  CloseCode,
  clientMessage,
  newRequestId,
  type ServerMessage,
} from "../protocol/messages";

export type ConnectionStatus = "connecting" | "online" | "offline" | "unauthorized" | "outdated";

export interface DeckClientListener {
  onStatus(status: ConnectionStatus, detail?: { retryInMs?: number; reason?: string }): void;
  onMessage(message: ServerMessage): void;
  /** Optional low-level lifecycle trace for diagnostics. */
  onTrace?(event: string): void;
}

export interface DeckClientOptions {
  url: string;
  token: string;
  listener: DeckClientListener;
  createSocket?: (url: string) => WebSocket;
  /** Base and cap for exponential backoff, in ms. */
  backoffBaseMs?: number;
  backoffMaxMs?: number;
  heartbeatMs?: number;
  /** Give up on a connection attempt that has not reached WELCOME within this time. */
  connectTimeoutMs?: number;
  /** Close the socket if nothing arrives for this long (half-open Wi-Fi drop). */
  staleAfterMs?: number;
  random?: () => number;
}

const AUTH_CLOSE_CODES = new Set<number>([CloseCode.AUTH_FAILED, CloseCode.DEVICE_REVOKED]);

export class DeckClient {
  private socket: WebSocket | null = null;
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private connectTimer: ReturnType<typeof setTimeout> | null = null;
  private lastMessageAt = 0;
  private stopped = false;
  private readonly opts: Required<Omit<DeckClientOptions, "listener" | "url" | "token">>;

  constructor(private readonly config: DeckClientOptions) {
    this.opts = {
      createSocket: config.createSocket ?? ((url) => new WebSocket(url)),
      backoffBaseMs: config.backoffBaseMs ?? 500,
      backoffMaxMs: config.backoffMaxMs ?? 15_000,
      heartbeatMs: config.heartbeatMs ?? 10_000,
      connectTimeoutMs: config.connectTimeoutMs ?? 4_000,
      staleAfterMs: config.staleAfterMs ?? 25_000,
      random: config.random ?? Math.random,
    };
  }

  start(): void {
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.trace("stop");
    this.stopped = true;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000);
  }

  /** Reconnect immediately (e.g. tab became visible, network came back). */
  nudge(): void {
    this.trace(`nudge readyState=${this.socket?.readyState ?? "none"}`);
    if (this.stopped) return;
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    this.attempt = 0;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.open();
  }

  /** Send ACTION_EXECUTE; returns the requestId, or null if offline. */
  /** Tell the PC whether a monitoring page is on screen (it only samples while one is). */
  setMonitoring(active: boolean): boolean {
    return this.send(clientMessage("MONITOR_SUBSCRIBE", { active }));
  }

  executeButton(buttonId: string, confirmed = false): string | null {
    const requestId = newRequestId();
    const payload = confirmed ? { buttonId, confirmed } : { buttonId };
    return this.send(clientMessage("ACTION_EXECUTE", payload, requestId)) ? requestId : null;
  }

  private send(data: unknown): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(data));
    return true;
  }

  private open(): void {
    this.clearTimers();
    this.config.listener.onStatus("connecting");
    this.trace(`open ${this.config.url} attempt=${this.attempt}`);
    let socket: WebSocket;
    try {
      socket = this.opts.createSocket(this.config.url);
    } catch (error) {
      this.trace(`create failed: ${String(error)}`);
      this.scheduleReconnect("Could not open connection");
      return;
    }
    this.socket = socket;
    // A handshake can hang silently (Wi-Fi handover, suspended tab); never wait forever.
    this.connectTimer = setTimeout(() => {
      this.connectTimer = null;
      if (socket !== this.socket) return;
      this.trace(`connect timeout readyState=${socket.readyState}`);
      this.abandon(socket, "Connection timed out");
    }, this.opts.connectTimeoutMs);

    socket.onopen = () => {
      this.trace(`onopen current=${socket === this.socket}`);
      if (socket !== this.socket) return;
      this.lastMessageAt = Date.now();
      socket.send(JSON.stringify(clientMessage("HELLO", { token: this.config.token, clientVersion: "1.0.0" })));
      this.startHeartbeat();
    };

    socket.onmessage = (event) => {
      if (socket !== this.socket) return;
      this.lastMessageAt = Date.now();
      let message: ServerMessage;
      try {
        message = JSON.parse(String(event.data)) as ServerMessage;
      } catch {
        return;
      }
      if (message.type === "WELCOME") {
        this.trace("welcome");
        this.attempt = 0;
        if (this.connectTimer) clearTimeout(this.connectTimer);
        this.connectTimer = null;
        this.config.listener.onStatus("online");
      }
      this.config.listener.onMessage(message);
    };

    socket.onclose = (event) => {
      this.trace(`onclose code=${event.code} current=${socket === this.socket}`);
      if (socket !== this.socket) return;
      this.socket = null;
      this.clearTimers();
      if (this.stopped) return;
      if (event.code === CloseCode.UNSUPPORTED_VERSION) {
        // The PC was updated: this page's code is older than the server.
        this.stopped = true;
        this.config.listener.onStatus("outdated");
        return;
      }
      if (AUTH_CLOSE_CODES.has(event.code)) {
        this.stopped = true;
        this.config.listener.onStatus("unauthorized", { reason: "This iPad is no longer paired." });
        return;
      }
      this.scheduleReconnect();
    };
    // onerror is always followed by onclose; nothing to do here.
    socket.onerror = () => this.trace("onerror");
  }

  private abandon(socket: WebSocket, reason: string): void {
    this.socket = null;
    this.clearTimers();
    try {
      socket.close();
    } catch {
      /* already closing */
    }
    this.scheduleReconnect(reason);
  }

  private trace(event: string): void {
    this.config.listener.onTrace?.(event);
  }

  private scheduleReconnect(reason?: string): void {
    const exp = Math.min(this.opts.backoffMaxMs, this.opts.backoffBaseMs * 2 ** this.attempt);
    // Full jitter in the upper half avoids synchronized retries from several iPads.
    const delay = Math.round(exp / 2 + (this.opts.random() * exp) / 2);
    this.attempt += 1;
    this.config.listener.onStatus("offline", { retryInMs: delay, reason });
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, delay);
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (Date.now() - this.lastMessageAt > this.opts.staleAfterMs) {
        // No PONG for too long: the link is dead even if the socket looks open.
        if (this.socket) this.abandon(this.socket, "Connection timed out");
        return;
      }
      this.send(clientMessage("PING"));
    }, this.opts.heartbeatMs);
  }

  private clearTimers(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.connectTimer) clearTimeout(this.connectTimer);
    this.heartbeatTimer = null;
    this.reconnectTimer = null;
    this.connectTimer = null;
  }
}

export function defaultSocketUrl(location: Location = window.location): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws`;
}
