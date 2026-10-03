import { memo, useEffect, useMemo, useState, type CSSProperties } from "react";
import { BuiltinIcon } from "../icons/BuiltinIcon";
import { computeGridLayout, metricsFor, type SizeClass } from "../layout/gridLayout";
import { useElementSize } from "../layout/useMeasure";
import type { MonitorView } from "../connection/deckStore";
import { buildTiles, type Tile } from "./tiles";
import "./monitor.css";

/** Readings older than this many intervals (and at least STALE_MIN_MS) count as stale. */
const STALE_INTERVALS = 3;
const STALE_MIN_MS = 12_000;

interface Props {
  monitor: MonitorView | null;
  sizeClass: SizeClass;
  /** False while the PC connection is down: values are kept but shown as not current. */
  online: boolean;
  /** Shown above the grid; the editor preview hides it. */
  showStatus?: boolean;
}

/** System Monitoring readouts, laid out by the same responsive grid as keys. */
export function MonitorGrid({ monitor, sizeClass, online, showStatus = true }: Props) {
  const [frameRef, frame] = useElementSize<HTMLDivElement>();
  const tiles = useMemo(() => (monitor ? buildTiles(monitor.payload) : []), [monitor]);
  const now = useNow(1000);
  const interval = monitor?.payload.intervalMs ?? 1000;
  const age = monitor ? now - monitor.receivedAt : Infinity;
  const stale = !online || age > Math.max(STALE_INTERVALS * interval, STALE_MIN_MS);

  const layout = useMemo(
    () =>
      frame.width > 0 && tiles.length
        ? computeGridLayout({ width: frame.width, height: frame.height, count: tiles.length, metrics: metricsFor(sizeClass) })
        : null,
    [frame.width, frame.height, tiles.length, sizeClass],
  );

  return (
    <div className="monitor">
      {showStatus && (
        <p className="monitor__status" role="status" data-stale={stale || undefined}>
          <span className="led" data-tone={stale ? (online ? "busy" : "error") : "online"} aria-hidden="true" />
          {!online ? "Connection lost · reconnecting…" : !monitor ? "Waiting for the PC…" : stale ? "No recent update" : `Live · every ${interval / 1000} s`}
        </p>
      )}
      <div ref={frameRef} className="deck-grid-frame monitor__frame" data-scroll={layout && !layout.fits ? "" : undefined}>
        {!monitor ? (
          <p className="deck-empty">{online ? "Reading this PC's sensors…" : "Reconnecting to the PC…"}</p>
        ) : tiles.length === 0 ? (
          <p className="deck-empty">All tiles are switched off. Turn some on in the editor on your PC.</p>
        ) : (
          layout && (
            <div
              className="deck-grid monitor__grid"
              data-stale={stale || undefined}
              style={{ "--cols": layout.columns, "--key": `${layout.key}px`, "--gap": `${layout.gap}px` } as CSSProperties}
              aria-label="System monitoring"
            >
              {tiles.map((tile) => (
                <MonitorTile key={tile.key} tile={tile} history={tile.history ? monitor.history[tile.history] : undefined} />
              ))}
            </div>
          )
        )}
      </div>
    </div>
  );
}

export const MonitorTile = memo(function MonitorTile({ tile, history }: { tile: Tile; history?: number[] }) {
  return (
    <article className="readout" data-level={tile.level ?? undefined} data-status={tile.status} data-metric-long={tile.value.length > 6 || undefined} aria-label={`${tile.title}: ${tile.value}${tile.detail ? `, ${tile.detail}` : ""}`}>
      {history && history.length > 1 && <Sparkline values={history} max={tile.historyMax} />}
      <header className="readout__head">
        <BuiltinIcon name={tile.icon} className="readout__icon" />
        <span className="readout__title">{tile.title}</span>
        {tile.level && tile.level !== "normal" && (
          <span className="led readout__led" data-tone={tile.level === "high" ? "error" : "busy"} aria-hidden="true" />
        )}
      </header>
      <p className="readout__value">{tile.value}</p>
      <p className="readout__detail">{tile.detail}</p>
    </article>
  );
});

/** A quiet trace of recent values behind the reading. Plain SVG, no chart library. */
function Sparkline({ values, max }: { values: number[]; max?: number }) {
  const top = max ?? Math.max(...values, 1);
  const n = values.length;
  const points = values.map((v, i) => `${((i / (n - 1)) * 100).toFixed(2)},${(100 - (Math.min(v, top) / top) * 100).toFixed(2)}`);
  return (
    <svg className="readout__spark" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <polygon points={`0,100 ${points.join(" ")} 100,100`} className="readout__spark-fill" />
      <polyline points={points.join(" ")} className="readout__spark-line" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function useNow(stepMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), stepMs);
    return () => clearInterval(timer);
  }, [stepMs]);
  return now;
}
