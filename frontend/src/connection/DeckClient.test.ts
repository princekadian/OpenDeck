import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeckClient, type ConnectionStatus } from "./DeckClient";
import { FakeSocket, createFakeSocket } from "../test/fakeSocket";

function makeClient() {
  const statuses: Array<{ status: ConnectionStatus; retryInMs?: number }> = [];
  const messages: unknown[] = [];
  const client = new DeckClient({
    url: "ws://pc/ws",
    token: "t".repeat(43),
    createSocket: createFakeSocket,
    random: () => 1, // deterministic: delay = full exponential step
    listener: {
      onStatus: (status, detail) => statuses.push({ status, retryInMs: detail?.retryInMs }),
      onMessage: (m) => messages.push(m),
    },
  });
  return { client, statuses, messages };
}

describe("DeckClient", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
  });
  afterEach(() => vi.useRealTimers());

  it("sends HELLO with the token on open and reports online after WELCOME", () => {
    const { client, statuses } = makeClient();
    client.start();
    const socket = FakeSocket.latest();
    socket.serverOpen();
    expect(socket.sent[0]).toMatchObject({ version: 2, type: "HELLO", payload: { token: "t".repeat(43) } });
    expect(statuses.at(-1)?.status).toBe("connecting");
    socket.serverSend({ type: "WELCOME", payload: { serverName: "PC" } });
    expect(statuses.at(-1)?.status).toBe("online");
  });

  it("reconnects with exponential backoff capped at the maximum", () => {
    const { client, statuses } = makeClient();
    client.start();
    const delays: number[] = [];
    for (let i = 0; i < 7; i++) {
      FakeSocket.latest().serverClose(1006);
      delays.push(statuses.at(-1)!.retryInMs!);
      vi.advanceTimersByTime(delays.at(-1)!);
    }
    expect(delays).toEqual([500, 1000, 2000, 4000, 8000, 15000, 15000]);
    expect(FakeSocket.instances).toHaveLength(8);
  });

  it("resets backoff after a successful session", () => {
    const { client, statuses } = makeClient();
    client.start();
    FakeSocket.latest().serverClose();
    vi.advanceTimersByTime(500);
    FakeSocket.latest().serverClose();
    vi.advanceTimersByTime(1000);
    const socket = FakeSocket.latest();
    socket.serverOpen();
    socket.serverSend({ type: "WELCOME", payload: {} });
    socket.serverClose();
    expect(statuses.at(-1)).toEqual({ status: "offline", retryInMs: 500 });
  });

  it("stops and reports unauthorized when the device is rejected", () => {
    const { client, statuses } = makeClient();
    client.start();
    FakeSocket.latest().serverOpen();
    FakeSocket.latest().serverClose(4003);
    expect(statuses.at(-1)?.status).toBe("unauthorized");
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("detects a silent dead link via heartbeat and reconnects", () => {
    const { client, statuses } = makeClient();
    client.start();
    const socket = FakeSocket.latest();
    socket.serverOpen();
    socket.serverSend({ type: "WELCOME", payload: {} });
    vi.advanceTimersByTime(10_000);
    expect(socket.sent.some((m) => m.type === "PING")).toBe(true);
    vi.advanceTimersByTime(20_000); // no PONG arrives
    expect(statuses.at(-1)?.status).toBe("offline");
  });

  it("nudge reconnects immediately while waiting to retry", () => {
    const { client } = makeClient();
    client.start();
    FakeSocket.latest().serverClose();
    client.nudge();
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("returns null when executing while offline", () => {
    const { client } = makeClient();
    client.start();
    expect(client.executeButton("b1")).toBeNull();
  });
});
