import { useMemo, useState } from "react";
import qrcode from "qrcode-generator";
import type { ServerState } from "./api";

const STATE_TEXT: Record<ServerState, string> = {
  running: "Running",
  stopped: "Stopped",
  starting: "Starting…",
  stopping: "Stopping…",
  error: "Error",
};

/** Server state as a symbol plus words, so it never depends on colour alone. */
export function StateChip({ state, size = "md" }: { state: ServerState | "engine-down"; size?: "sm" | "md" }) {
  const text = state === "engine-down" ? "Engine not responding" : STATE_TEXT[state];
  return (
    <span className="state-chip" data-state={state} data-size={size}>
      <StateGlyph state={state} />
      {text}
    </span>
  );
}

function StateGlyph({ state }: { state: ServerState | "engine-down" }) {
  // ● running  ○ stopped  ◌ starting/stopping  ⚠ error
  if (state === "running") return <svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="currentColor" /></svg>;
  if (state === "stopped") return <svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>;
  if (state === "starting" || state === "stopping")
    return <svg viewBox="0 0 12 12" aria-hidden="true" className="state-chip__spin"><circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeDasharray="3 2.3" /></svg>;
  return (
    <svg viewBox="0 0 12 12" aria-hidden="true">
      <path d="M6 1.2 11.2 10.6H.8Z" fill="currentColor" />
      <path d="M6 4.6v2.8M6 8.8v.2" stroke="#1a1b1e" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

/** QR code drawn locally as SVG (no network). */
export function QrCode({ text, size = 168 }: { text: string; size?: number }) {
  const { path, count } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    const n = qr.getModuleCount();
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c + 4} ${r + 4}h1v1h-1z`;
    return { path: d, count: n + 8 };
  }, [text]);
  return (
    <svg className="qr" width={size} height={size} viewBox={`0 0 ${count} ${count}`} role="img" aria-label={`QR code for ${text}`} shapeRendering="crispEdges">
      <rect width={count} height={count} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

export function Panel({ title, actions, children, className }: { title: string; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`panel ${className ?? ""}`} aria-label={title}>
      <header className="panel__head">
        <h2 className="panel__title">{title}</h2>
        {actions && <div className="panel__actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Facts({ items }: { items: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="facts">
      {items.map(([k, v]) => (
        <div key={k} className="facts__row">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
