import { useCallback, useEffect, useRef, useState } from "react";
import { bridge, desktopApi, whenBridgeReady, type HostState, type ServerInfo, type SystemInfo } from "./api";

/**
 * Live server state without polling: a long-poll request waits until the state changes.
 * `engineDown` turns true when the engine stops answering (crash, restart).
 */
export function useServerInfo(): { info: ServerInfo | null; engineDown: boolean; refresh: (next?: ServerInfo) => void } {
  const [info, setInfo] = useState<ServerInfo | null>(null);
  const [engineDown, setEngineDown] = useState(false);
  const version = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      while (!stopped) {
        try {
          const next = version.current === 0 ? await desktopApi.server() : await desktopApi.serverWait(version.current, controller.signal);
          version.current = next.version || 1;
          setInfo(next);
          setEngineDown(false);
        } catch (e) {
          if ((e as Error).name === "AbortError") return;
          setEngineDown(true);
          version.current = 0;
          await new Promise((resolve) => (timer = setTimeout(resolve, 1500)));
        }
      }
    };
    void loop();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  const refresh = useCallback((next?: ServerInfo) => {
    if (next) setInfo(next);
  }, []);
  return { info, engineDown, refresh };
}

/** Desktop app state from the host (process ids, engine crash), when running in the window. */
export function useHostState(): HostState | null {
  const [state, setState] = useState<HostState | null>(null);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const api = bridge();
      if (api) {
        try {
          const next = await api.host_state();
          if (alive) setState(next);
        } catch {
          /* host busy */
        }
      }
      if (alive) timer = setTimeout(tick, 5000);
    };
    const cancel = whenBridgeReady(() => void tick());
    return () => {
      alive = false;
      clearTimeout(timer);
      cancel();
    };
  }, []);
  return state;
}

/** CPU/RAM for the status bar: a cheap call every few seconds, only while the window is visible. */
export function useSystemInfo(host: HostState | null, everyMs = 4000): SystemInfo | null {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const pids = useRef(host);
  pids.current = host;
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (document.visibilityState === "visible") {
        try {
          const next = await desktopApi.system(pids.current?.hostPid, pids.current?.uiPid);
          if (alive) setInfo(next);
        } catch {
          /* engine down: the shell shows that separately */
        }
      }
      if (alive) timer = setTimeout(tick, everyMs);
    };
    void tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [everyMs]);
  return info;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d} d ${h} h`;
  if (h) return `${h} h ${m} min`;
  if (m) return `${m} min`;
  return `${Math.max(0, Math.round(seconds))} s`;
}

export function deviceType(userAgent: string): string {
  const ua = userAgent.toLowerCase();
  if (/ipad/.test(ua)) return "iPad";
  if (/iphone/.test(ua)) return "iPhone";
  if (/android/.test(ua)) return /mobile/.test(ua) ? "Android phone" : "Android tablet";
  if (/windows/.test(ua)) return "Windows PC";
  // iPadOS Safari reports itself as a Mac; the two can't be told apart from the header.
  if (/macintosh/.test(ua)) return "iPad or Mac";
  return ua ? "Browser" : "Unknown";
}
