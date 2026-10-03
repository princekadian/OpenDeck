import { describe, expect, it } from "vitest";
import { byLogicalPosition, computeGridLayout, metricsFor, sizeClassFor } from "./gridLayout";

// Grid area = viewport minus header (56), page bar (~68), safe areas and padding.
function layoutFor(viewportW: number, viewportH: number, count: number) {
  const sizeClass = sizeClassFor(viewportW, viewportH);
  const pad = sizeClass === "compact" ? 24 : 48;
  return computeGridLayout({
    width: viewportW - pad,
    height: viewportH - 56 - 68 - pad,
    count,
    metrics: metricsFor(sizeClass),
  });
}

describe("sizeClassFor", () => {
  it("classifies by real viewport size", () => {
    expect(sizeClassFor(390, 844)).toBe("compact"); // iPhone portrait
    expect(sizeClassFor(844, 390)).toBe("compact"); // iPhone landscape
    expect(sizeClassFor(744, 1133)).toBe("regular"); // iPad mini portrait
    expect(sizeClassFor(1180, 820)).toBe("regular"); // iPad landscape
    expect(sizeClassFor(1920, 1000)).toBe("wide"); // desktop
  });
});

describe("computeGridLayout", () => {
  const cases: Array<[string, number, number, number]> = [
    ["iPhone portrait", 390, 844, 8],
    ["iPhone landscape", 844, 390, 8],
    ["Android small", 360, 740, 15],
    ["iPad mini portrait", 744, 1133, 15],
    ["iPad landscape", 1180, 820, 15],
    ["iPad Pro landscape", 1366, 1024, 32],
    ["laptop", 1366, 680, 15],
    ["desktop", 1920, 950, 8],
    ["ultrawide", 3440, 1300, 15],
  ];

  it.each(cases)("%s keeps keys on screen, touchable and without horizontal overflow", (_, w, h, n) => {
    const sizeClass = sizeClassFor(w, h);
    const metrics = metricsFor(sizeClass);
    const width = w - (sizeClass === "compact" ? 24 : 48);
    const layout = layoutFor(w, h, n);
    const gridWidth = layout.columns * layout.key + (layout.columns - 1) * layout.gap;
    expect(gridWidth).toBeLessThanOrEqual(width);
    expect(layout.key).toBeGreaterThanOrEqual(Math.min(metrics.minKey, width));
    expect(layout.key).toBeLessThanOrEqual(metrics.maxKey);
    expect(layout.columns * layout.rows).toBeGreaterThanOrEqual(n);
  });

  it("uses fewer columns on phones and more on wide screens for the same page", () => {
    const phone = layoutFor(390, 844, 8);
    const tabletPortrait = layoutFor(820, 1180, 8);
    const tabletLandscape = layoutFor(1180, 820, 8);
    const desktop = layoutFor(1920, 950, 8);
    expect(phone.columns).toBe(2);
    expect(tabletPortrait.columns).toBeLessThan(tabletLandscape.columns);
    expect(desktop.columns).toBeGreaterThanOrEqual(tabletLandscape.columns);
  });

  it("shows a full 15-key page on an iPad in landscape as 5 × 3 without scrolling", () => {
    expect(layoutFor(1180, 820, 15)).toMatchObject({ columns: 5, rows: 3, fits: true });
  });

  it("falls back to vertical scrolling with comfortable keys when the page cannot fit", () => {
    const layout = layoutFor(390, 844, 32);
    expect(layout.fits).toBe(false);
    expect(layout.columns).toBe(2);
    expect(layout.key).toBeGreaterThanOrEqual(140);
  });

  it("keeps a sparse page compact instead of stretching keys", () => {
    const layout = layoutFor(1920, 950, 3);
    expect(layout).toMatchObject({ columns: 3, rows: 1 });
    expect(layout.key).toBe(metricsFor("wide").maxKey);
  });

  it("never returns zero columns for tiny or empty containers", () => {
    const layout = computeGridLayout({ width: 80, height: 80, count: 4, metrics: metricsFor("compact") });
    expect(layout.columns).toBe(1);
    expect(layout.key).toBeLessThanOrEqual(80);
  });
});

describe("computeGridLayout row balance", () => {
  it.each([
    ["laptop", 1366, 680],
    ["desktop", 1920, 950],
  ])("does not strand a lone key in the last row on a %s", (_, w, h) => {
    const layout = layoutFor(w, h, 15);
    const lastRow = 15 - (layout.rows - 1) * layout.columns;
    expect(lastRow).toBeGreaterThanOrEqual(Math.ceil(layout.columns / 2));
  });
});

describe("byLogicalPosition", () => {
  it("orders by configured position regardless of input order", () => {
    const items = [
      { id: "c", sortOrder: 2 },
      { id: "b", sortOrder: 1 },
      { id: "a", sortOrder: 0 },
    ];
    expect(byLogicalPosition(items).map((i) => i.id)).toEqual(["a", "b", "c"]);
  });
});
