// Responsive key-grid layout. Pure and data-driven: the stored page keeps logical
// row/col positions (they define key order); this decides the *visual* grid for the
// space actually available, so one page config works from phones to ultrawide monitors.

export type SizeClass = "compact" | "regular" | "wide";

export interface LayoutMetrics {
  /** Smallest acceptable key edge, in CSS px. Below this the grid scrolls instead. */
  minKey: number;
  /** Largest key edge; beyond this extra space becomes margin. */
  maxKey: number;
  /** Key edge to aim for when the grid cannot fit and must scroll. */
  comfortKey: number;
  gap: number;
}

const METRICS: Record<SizeClass, LayoutMetrics> = {
  // Phones: fewer, larger keys for thumbs.
  compact: { minKey: 96, maxKey: 168, comfortKey: 140, gap: 10 },
  // Tablets and small laptops.
  regular: { minKey: 104, maxKey: 200, comfortKey: 160, gap: 14 },
  // Desktop and ultrawide monitors: more columns, keys stay a sensible size.
  wide: { minKey: 96, maxKey: 184, comfortKey: 150, gap: 16 },
};

/** Classify by the viewport's real dimensions, never by user agent. */
export function sizeClassFor(viewportWidth: number, viewportHeight: number): SizeClass {
  if (Math.min(viewportWidth, viewportHeight) < 600) return "compact";
  if (viewportWidth >= 1400) return "wide";
  return "regular";
}

export function metricsFor(sizeClass: SizeClass): LayoutMetrics {
  return METRICS[sizeClass];
}

export interface GridLayout {
  columns: number;
  rows: number;
  key: number;
  gap: number;
  /** True when every key is visible without scrolling. */
  fits: boolean;
}

export interface LayoutInput {
  width: number;
  height: number;
  count: number;
  metrics: LayoutMetrics;
}

/** Layouts whose keys are within this fraction of the largest are judged on shape instead. */
const KEY_TOLERANCE = 0.06;

export function computeGridLayout({ width, height, count, metrics }: LayoutInput): GridLayout {
  const { minKey, maxKey, comfortKey, gap } = metrics;
  const n = Math.max(1, count);
  const keyForWidth = (c: number) => (width - (c - 1) * gap) / c;
  const keyForHeight = (r: number) => (height - (r - 1) * gap) / r;
  const maxColumns = Math.max(1, Math.floor((width + gap) / (minKey + gap)));

  // 1. Show everything at once. Among arrangements with near-maximal keys, prefer a
  //    full last row (a lone key beside empty sockets looks broken), then the shape
  //    that best matches the available area.
  const aspect = width / Math.max(1, height);
  const candidates: Array<GridLayout & { cost: number }> = [];
  for (let c = 1; c <= Math.min(n, maxColumns); c++) {
    const r = Math.ceil(n / c);
    const key = Math.floor(Math.min(keyForWidth(c), keyForHeight(r), maxKey));
    if (key < minKey) continue;
    // A slightly short last row is fine; a mostly empty one is not.
    const emptyShare = (c * r - n) / c;
    const emptyCost = emptyShare > 0.5 ? emptyShare : emptyShare * 0.25;
    const shapeError = Math.abs(Math.log(c / r / aspect));
    candidates.push({ columns: c, rows: r, key, gap, fits: true, cost: emptyCost + 0.5 * shapeError });
  }
  if (candidates.length > 0) {
    const largest = Math.max(...candidates.map((l) => l.key));
    const best = candidates
      .filter((l) => l.key >= largest * (1 - KEY_TOLERANCE))
      .reduce((a, b) => (b.cost < a.cost ? b : a));
    return { columns: best.columns, rows: best.rows, key: best.key, gap: best.gap, fits: true };
  }

  // 2. Too many keys for the screen: pick comfortable columns and scroll vertically.
  const columns = Math.max(1, Math.min(n, maxColumns, Math.floor((width + gap) / (comfortKey + gap)) || 1));
  const key = Math.floor(Math.min(Math.max(keyForWidth(columns), Math.min(minKey, width)), maxKey));
  return { columns, rows: Math.ceil(n / columns), key, gap, fits: false };
}

/** Logical order as configured on the PC. Reflow never reorders keys. */
export function byLogicalPosition<T extends { sortOrder: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => a.sortOrder - b.sortOrder);
}
