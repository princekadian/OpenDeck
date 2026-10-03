import { useElementSize } from "../layout/useMeasure";
import type { Page } from "../protocol/messages";

interface Props {
  pages: Page[];
  activePageId: string | null;
  onSelect: (pageId: string) => void;
}

/** Below this per-tab width, labels stop being comfortably tappable. */
const MIN_TAB_WIDTH = 96;
const TAB_GAP = 8;

export function PageBar({ pages, activePageId, onSelect }: Props) {
  const [ref, size] = useElementSize<HTMLElement>();
  const tabsFit = size.width === 0 || pages.length * (MIN_TAB_WIDTH + TAB_GAP) - TAB_GAP <= size.width;

  return (
    <nav ref={ref} className="page-bar" aria-label="Pages">
      {tabsFit ? (
        pages.map((page) => (
          <button
            key={page.id}
            type="button"
            className="page-bar__tab"
            aria-current={page.id === activePageId ? "page" : undefined}
            onClick={() => onSelect(page.id)}
          >
            {page.name}
          </button>
        ))
      ) : (
        <PageStepper pages={pages} activePageId={activePageId} onSelect={onSelect} />
      )}
    </nav>
  );
}

/** Narrow screens: previous / current page (opens the native picker) / next. */
function PageStepper({ pages, activePageId, onSelect }: Props) {
  const index = Math.max(0, pages.findIndex((p) => p.id === activePageId));
  const current = pages[index];
  const go = (delta: number) => onSelect(pages[(index + delta + pages.length) % pages.length].id);

  return (
    <div className="page-stepper">
      <button type="button" className="page-stepper__arrow" onClick={() => go(-1)} aria-label="Previous page">
        <Chevron direction="left" />
      </button>
      <label className="page-stepper__current">
        <span className="page-stepper__name">{current?.name}</span>
        <span className="page-stepper__count">
          {index + 1} of {pages.length}
        </span>
        {/* Invisible native select on top: iOS/Android show their own page picker. */}
        <select
          className="page-stepper__select"
          value={current?.id}
          onChange={(e) => onSelect(e.target.value)}
          aria-label="Choose page"
        >
          {pages.map((page) => (
            <option key={page.id} value={page.id}>
              {page.name}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="page-stepper__arrow" onClick={() => go(1)} aria-label="Next page">
        <Chevron direction="right" />
      </button>
    </div>
  );
}

function Chevron({ direction }: { direction: "left" | "right" }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={direction === "left" ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7"} />
    </svg>
  );
}
