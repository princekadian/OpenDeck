import { useMemo, type CSSProperties } from "react";
import type { DeckState } from "../connection/deckStore";
import { BuiltinIcon } from "../icons/BuiltinIcon";
import { byLogicalPosition, computeGridLayout, metricsFor, type SizeClass } from "../layout/gridLayout";
import { useElementSize } from "../layout/useMeasure";
import type { Page } from "../protocol/messages";
import { DeckKey } from "./DeckKey";

interface Props {
  page: Page;
  deck: DeckState;
  sizeClass: SizeClass;
  onPress: (buttonId: string) => void;
  onBack: () => void;
}

/** One grid for pages and folders alike: it shows the keys of the current container. */
export function DeckGrid({ page, deck, sizeClass, onPress, onBack }: Props) {
  const [frameRef, frame] = useElementSize<HTMLDivElement>();
  const folderId = deck.folderStack.at(-1) ?? null;
  const buttons = useMemo(
    () => byLogicalPosition(deck.buttons.filter((b) => b.pageId === page.id && (b.parentId ?? null) === folderId)),
    [deck.buttons, page.id, folderId],
  );
  const inFolder = folderId !== null;
  // Inside a folder a Back key is generated in the last slot; it is not stored anywhere.
  const slots = buttons.length + (inFolder ? 1 : 0);
  const offline = deck.status !== "online";

  const layout = useMemo(
    () =>
      frame.width > 0
        ? computeGridLayout({ width: frame.width, height: frame.height, count: slots, metrics: metricsFor(sizeClass) })
        : null,
    [frame.width, frame.height, slots, sizeClass],
  );
  const sockets = layout && slots > 0 ? layout.columns * layout.rows - slots : 0;

  return (
    <div ref={frameRef} className="deck-grid-frame" data-scroll={layout && !layout.fits ? "" : undefined}>
      {slots === 0 ? (
        <p className="deck-empty">No keys on this page yet. Add keys in the editor on your PC.</p>
      ) : (
        layout && (
          <div
            key={folderId ?? page.id}
            className="deck-grid"
            data-enter={inFolder ? "folder" : undefined}
            style={{ "--cols": layout.columns, "--key": `${layout.key}px`, "--gap": `${layout.gap}px` } as CSSProperties}
            aria-label={`${page.name} keys`}
          >
            {buttons.map((button) => (
              <DeckKey
                key={button.id}
                button={button}
                state={deck.states[button.id]}
                feedback={deck.feedback[button.id]}
                disabled={offline && button.kind !== "folder"}
                onPress={onPress}
              />
            ))}
            {inFolder && buttons.length === 0 && <p className="deck-folder-empty">This folder is empty.</p>}
            {Array.from({ length: sockets }, (_, i) => (
              <span key={`socket-${i}`} className="deck-socket" aria-hidden="true" />
            ))}
            {inFolder && (
              <button type="button" className="deck-key deck-key--back" onClick={onBack} aria-label="Back">
                <BuiltinIcon name="back" className="deck-key__icon" />
                <span className="deck-key__label">Back</span>
                <span className="deck-key__status" aria-hidden="true" />
              </button>
            )}
          </div>
        )
      )}
    </div>
  );
}
