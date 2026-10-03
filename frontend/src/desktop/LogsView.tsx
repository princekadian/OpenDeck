import { useEffect, useMemo, useRef, useState } from "react";
import { bridge, desktopApi, type LogEntry } from "./api";

const MAX_ENTRIES = 5000;
const SHOWN = 1500;
const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
type MinLevel = "ALL" | (typeof LEVELS)[number];

/** Server log, live (server-sent events, no polling), plus the desktop app's log file. */
export function LogsView({ notify }: { notify: (text: string, error?: boolean) => void }) {
  const [source, setSource] = useState<"server" | "desktop">("server");
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [fileLines, setFileLines] = useState<string[]>([]);
  const [level, setLevel] = useState<MinLevel>("ALL");
  const [component, setComponent] = useState("");
  const [query, setQuery] = useState("");
  const [paused, setPaused] = useState(false);
  const [follow, setFollow] = useState(true);
  const [connected, setConnected] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const lastSeq = useRef(0);
  const pending = useRef<LogEntry[]>([]);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const listRef = useRef<HTMLDivElement>(null);

  // Live stream of the engine log.
  useEffect(() => {
    if (source !== "server") return;
    const stream = new EventSource(`/api/admin/logs/stream?after=${lastSeq.current}`);
    let flush: ReturnType<typeof setTimeout> | undefined;
    stream.onopen = () => setConnected(true);
    stream.onerror = () => setConnected(false); // EventSource reconnects by itself
    stream.onmessage = (event) => {
      const entry = JSON.parse(event.data) as LogEntry;
      if (entry.seq <= lastSeq.current) return;
      lastSeq.current = entry.seq;
      pending.current.push(entry);
      // Batch renders: a burst of 200 lines is one update, not 200.
      flush ??= setTimeout(() => {
        flush = undefined;
        if (pausedRef.current) return;
        const add = pending.current;
        pending.current = [];
        setEntries((old) => [...old, ...add].slice(-MAX_ENTRIES));
      }, 150);
    };
    return () => {
      stream.close();
      clearTimeout(flush);
      setConnected(false);
    };
  }, [source]);

  // Resuming shows what arrived while paused.
  useEffect(() => {
    if (!paused && pending.current.length) {
      const add = pending.current;
      pending.current = [];
      setEntries((old) => [...old, ...add].slice(-MAX_ENTRIES));
    }
  }, [paused]);

  const loadFile = () => desktopApi.logFile("desktop", 2000).then((r) => setFileLines(r.lines), () => notify("Couldn't read the desktop log.", true));
  useEffect(() => {
    if (source === "desktop") void loadFile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  const components = useMemo(() => [...new Set(entries.map((e) => e.component))].sort(), [entries]);
  const visible = useMemo(() => {
    const min = level === "ALL" ? 0 : LEVELS.indexOf(level);
    const q = query.trim().toLowerCase();
    return entries
      .filter((e) => LEVELS.indexOf(e.level) >= min)
      .filter((e) => !component || e.component === component)
      .filter((e) => !q || e.message.toLowerCase().includes(q) || e.component.toLowerCase().includes(q))
      .slice(-SHOWN);
  }, [entries, level, component, query]);
  const visibleFile = useMemo(() => {
    const q = query.trim().toLowerCase();
    const min = level === "ALL" ? 0 : LEVELS.indexOf(level);
    return fileLines
      .filter((l) => !q || l.toLowerCase().includes(q))
      .filter((l) => min === 0 || LEVELS.slice(min).some((lv) => l.includes(` ${lv} `)))
      .slice(-SHOWN);
  }, [fileLines, query, level]);

  useEffect(() => {
    if (follow && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [visible, visibleFile, follow]);

  const asText = (list: LogEntry[]) => list.map(formatLine).join("\n");

  async function copySelection() {
    const chosen = visible.filter((e) => selected.has(e.seq));
    const text = source === "server" ? asText(chosen.length ? chosen : visible) : visibleFile.join("\n");
    await navigator.clipboard.writeText(text);
    notify(chosen.length ? `Copied ${chosen.length} lines` : "Copied the visible lines");
  }

  async function exportLog() {
    const text = source === "server" ? asText(visible) : visibleFile.join("\n");
    const name = `opendeck-${source}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.log`;
    const api = bridge();
    if (api) {
      if (await api.save_text(name, text)) notify("Log saved");
      return;
    }
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    link.download = name;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  function toggle(seq: number, range: boolean) {
    setSelected((old) => {
      const next = new Set(range ? old : []);
      if (range && old.size) {
        const last = Math.max(...old);
        const [a, b] = last < seq ? [last, seq] : [seq, last];
        for (const e of visible) if (e.seq >= a && e.seq <= b) next.add(e.seq);
      } else if (old.has(seq) && old.size === 1) {
        next.delete(seq);
      } else {
        next.add(seq);
      }
      return next;
    });
  }

  return (
    <div className="view logs">
      <header className="view__head">
        <h1 className="view__title">Logs</h1>
        <div className="seg" role="tablist" aria-label="Log">
          <button type="button" role="tab" aria-selected={source === "server"} className="seg__item" onClick={() => setSource("server")}>
            Server (live)
          </button>
          <button type="button" role="tab" aria-selected={source === "desktop"} className="seg__item" onClick={() => setSource("desktop")}>
            Desktop app
          </button>
        </div>
      </header>

      <div className="logs__toolbar">
        <input className="input logs__search" type="search" placeholder="Search" aria-label="Search logs" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="input input-narrow" aria-label="Level" value={level} onChange={(e) => setLevel(e.target.value as MinLevel)}>
          <option value="ALL">All levels</option>
          <option value="INFO">Info and above</option>
          <option value="WARNING">Warnings and above</option>
          <option value="ERROR">Errors and above</option>
          <option value="CRITICAL">Critical</option>
        </select>
        {source === "server" && (
          <select className="input input-narrow" aria-label="Component" value={component} onChange={(e) => setComponent(e.target.value)}>
            <option value="">All components</option>
            {components.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        )}
        <span className="logs__spacer" />
        {source === "server" ? (
          <>
            <label className="logs__check">
              <input type="checkbox" checked={paused} onChange={(e) => setPaused(e.target.checked)} /> Pause
            </label>
            <label className="logs__check">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Auto-scroll
            </label>
            <button type="button" className="btn btn-sm" onClick={() => { setEntries([]); setSelected(new Set()); }}>
              Clear view
            </button>
          </>
        ) : (
          <button type="button" className="btn btn-sm" onClick={() => void loadFile()}>
            Refresh
          </button>
        )}
        <button type="button" className="btn btn-sm" onClick={() => void copySelection()}>
          Copy
        </button>
        <button type="button" className="btn btn-sm" onClick={() => void exportLog()}>
          Save as…
        </button>
        <button type="button" className="btn btn-sm" onClick={() => desktopApi.open("logs")}>
          Open folder
        </button>
      </div>

      <div ref={listRef} className="logs__list" role="log" aria-live="off" onScroll={(e) => {
        const el = e.currentTarget;
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        if (!atBottom && follow) setFollow(false);
      }}>
        {source === "server" ? (
          visible.length === 0 ? (
            <p className="empty">{connected ? "No log entries match." : "Connecting to the engine log…"}</p>
          ) : (
            visible.map((e) => (
              <div
                key={e.seq}
                className="log-line"
                data-level={e.level}
                data-selected={selected.has(e.seq) || undefined}
                onClick={(ev) => toggle(e.seq, ev.shiftKey)}
              >
                <time className="log-line__time">{new Date(e.time * 1000).toLocaleTimeString([], { hour12: false })}</time>
                <span className="log-line__level">{e.level}</span>
                <span className="log-line__comp">{e.component}</span>
                <span className="log-line__msg">{e.message}</span>
              </div>
            ))
          )
        ) : visibleFile.length === 0 ? (
          <p className="empty">The desktop log is empty.</p>
        ) : (
          visibleFile.map((line, i) => (
            <div key={i} className="log-line log-line--raw" data-level={LEVELS.find((lv) => line.includes(` ${lv} `))}>
              {line}
            </div>
          ))
        )}
      </div>
      <p className="logs__foot field__hint">
        {source === "server"
          ? `${visible.length} of ${entries.length} entries shown${paused ? " · paused" : ""}${selected.size ? ` · ${selected.size} selected (Shift-click for a range)` : " · click lines to select"}`
          : `Last ${fileLines.length} lines of desktop.log`}
      </p>
    </div>
  );
}

function formatLine(e: LogEntry): string {
  const t = new Date(e.time * 1000);
  const stamp = `${t.toISOString().slice(0, 10)} ${t.toLocaleTimeString([], { hour12: false })}`;
  return `${stamp} ${e.level.padEnd(8)} ${e.component}: ${e.message}`;
}
