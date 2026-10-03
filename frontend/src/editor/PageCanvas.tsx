import type { CSSProperties, MouseEvent } from "react";
import { KeyIcon } from "../icons/KeyIcon";
import type { ButtonKind, EditorButton, EditorPage, EditorProfile, EditorTree } from "./api";
import { childrenOf, folderPath, selfAndDescendants } from "./folders";
import { menuAt, type MenuItem, type MenuRequest } from "./Menu";
import { MoreButton, PlusIcon } from "./Sidebar";
import { useReorder, type DragGhost } from "./useReorder";

interface Props {
  tree: EditorTree;
  profile: EditorProfile;
  page: EditorPage;
  /** Folder being edited; null = the page itself. */
  folderId: string | null;
  onOpenFolder: (folderId: string | null) => void;
  onSelectProfile: (profileId: string) => void;
  onAdd: (kind: ButtonKind) => void;
  onEditButton: (button: EditorButton) => void;
  onReorder: (ids: string[]) => void;
  /** Drag-and-drop into a folder, or out to an outer level (null = the page). */
  onMoveInto: (button: EditorButton, parentId: string | null) => void;
  buttonMenu: (button: EditorButton) => MenuItem[];
  pageMenu: (page: EditorPage) => MenuItem[];
  openMenu: (request: MenuRequest) => void;
}

const TILE_KEY = "--key";
// Drop keys: "in:<folderId>" for a folder tile, "up:<folderId|>" for a breadcrumb.
const PAGE_LEVEL = "";

export function PageCanvas(props: Props) {
  const { tree, profile, page, folderId, onOpenFolder, onAdd, onEditButton, onReorder, onMoveInto, buttonMenu, pageMenu, openMenu } = props;
  const path = folderPath(tree, page.id, folderId);
  const folder = path.at(-1) ?? null;
  const buttons = childrenOf(tree, page.id, folder?.id ?? null);
  const byId = new Map(tree.buttons.map((b) => [b.id, b]));
  const icons = new Map(tree.actions.map((a) => [a.type, a.icon]));
  const where = folder ? folder.label : page.name;

  const reorder = useReorder(
    buttons.map((b) => b.id),
    {
      onCommit: onReorder,
      onLongPress: (id, x, y) => {
        const b = byId.get(id);
        if (b) openMenu({ x, y, items: buttonMenu(b) });
      },
      drop: {
        accepts: (dragId, key) => {
          const [kind, id] = splitKey(key);
          if (kind === "up") return true; // outer levels can never be inside the dragged item
          return !selfAndDescendants(tree, dragId).has(id);
        },
        onDrop: (dragId, key) => {
          const b = byId.get(dragId);
          const [, id] = splitKey(key);
          if (b) onMoveInto(b, id === PAGE_LEVEL ? null : id);
        },
      },
    },
  );

  // Breadcrumb levels that sit above the current one accept dropped buttons.
  const crumbTarget = (levelId: string | null) => (folder ? reorder.bindTarget(`up:${levelId ?? PAGE_LEVEL}`) : undefined);
  const crumbOver = (levelId: string | null) => (reorder.over === `up:${levelId ?? PAGE_LEVEL}` ? "" : undefined);

  return (
    <section className="canvas" aria-labelledby="canvas-title">
      <header className="canvas__head">
        <div className="canvas__where">
          <nav className="crumbs" aria-label="Location">
            <ol className="crumbs__list">
              <li>
                <button type="button" className="crumbs__step" onClick={() => props.onSelectProfile(profile.id)}>
                  {profile.name}
                </button>
              </li>
              {folder && (
                <li>
                  <button
                    type="button"
                    ref={crumbTarget(null)}
                    data-drop-over={crumbOver(null)}
                    className="crumbs__step"
                    onClick={() => onOpenFolder(null)}
                  >
                    {page.name}
                  </button>
                </li>
              )}
              {path.slice(0, -1).map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    ref={crumbTarget(f.id)}
                    data-drop-over={crumbOver(f.id)}
                    className="crumbs__step"
                    onClick={() => onOpenFolder(f.id)}
                  >
                    {f.label}
                  </button>
                </li>
              ))}
            </ol>
          </nav>
          <h1 id="canvas-title" className="canvas__title">
            {folder && <FolderGlyph />}
            {where}
          </h1>
        </div>
        <div className="canvas__actions">
          {folder ? (
            <>
              <button type="button" className="btn" onClick={() => onOpenFolder(path.at(-2)?.id ?? null)}>
                <BackGlyph /> Back
              </button>
              <MoreButton
                label={`${folder.label} folder options`}
                onOpen={(el) => openMenu({ ...menuAt(el), items: buttonMenu(folder), returnFocus: el })}
              />
            </>
          ) : (
            <MoreButton label={`${page.name} options`} onOpen={(el) => openMenu({ ...menuAt(el), items: pageMenu(page), returnFocus: el })} />
          )}
          <button type="button" className="btn" onClick={() => onAdd("folder")}>
            <FolderGlyph /> Add folder
          </button>
          <button type="button" className="btn btn-primary" onClick={() => onAdd("action")}>
            <PlusIcon /> Add button
          </button>
        </div>
      </header>

      {buttons.length === 0 ? (
        <div className="canvas__empty">
          <p>{folder ? "This folder is empty. Devices show a Back key here automatically." : "No buttons on this page yet."}</p>
          <button type="button" className="btn" onClick={() => onAdd("action")}>
            Add the first button
          </button>
        </div>
      ) : (
        <>
          <p className="canvas__hint">
            {folder
              ? "Drag to reorder, onto a folder to move a button inside, or onto a name in the path above to move it out. Devices add a Back key after these."
              : "Drag to reorder, or onto a folder to move a button inside. Devices show these buttons in this order and fit them to their screen."}
          </p>
          <ul className="tile-grid" role="list" aria-label={`Buttons in ${where}`}>
            {reorder.order.map((id, index) => {
              const button = byId.get(id);
              if (!button) return null;
              const binding = reorder.bind(button.id);
              const isFolder = button.kind === "folder";
              const contextMenu = (e: MouseEvent) => {
                e.preventDefault();
                openMenu({ x: e.clientX, y: e.clientY, items: buttonMenu(button) });
              };
              const ref = (el: HTMLLIElement | null) => {
                binding.ref(el);
                if (isFolder) reorder.bindTarget(`in:${button.id}`, 0.18)(el);
              };
              const count = isFolder ? childrenOf(tree, page.id, button.id).length : 0;
              return (
                <li
                  key={button.id}
                  className="tile"
                  ref={ref}
                  data-dragging={binding["data-dragging"]}
                  data-drop-over={reorder.over === `in:${button.id}` ? "" : undefined}
                  onPointerDown={binding.onPointerDown}
                  onClickCapture={binding.onClickCapture}
                  onContextMenu={contextMenu}
                >
                  <button
                    type="button"
                    className="tile__key"
                    onClick={() => (isFolder ? onOpenFolder(button.id) : onEditButton(button))}
                    onKeyDown={binding.onKeyDown}
                    aria-label={
                      isFolder
                        ? `${button.label} folder, ${count} ${count === 1 ? "item" : "items"}, position ${index + 1}. Open`
                        : `${button.label || "Untitled"}, position ${index + 1}${button.enabled ? "" : ", disabled"}. Edit`
                    }
                    title={isFolder ? "Click to open · Alt + arrow keys to reorder" : "Click to edit · Alt + arrow keys to reorder"}
                  >
                    <TileFace button={button} fallback={icons.get(button.actionType)} />
                  </button>
                  <span className="tile__more">
                    <MoreButton
                      label={`${button.label || "Button"} options`}
                      onOpen={(el) => openMenu({ ...menuAt(el), items: buttonMenu(button), returnFocus: el })}
                    />
                  </span>
                </li>
              );
            })}
            <li className="tile tile--add">
              <button type="button" className="tile__key tile__add" onClick={() => onAdd("action")} aria-label="Add button">
                <PlusIcon />
              </button>
            </li>
          </ul>
        </>
      )}
      {reorder.ghost && byId.get(reorder.ghost.id) && (
        <TileGhost
          ghost={reorder.ghost}
          button={byId.get(reorder.ghost.id)!}
          fallback={icons.get(byId.get(reorder.ghost.id)!.actionType)}
          dropping={reorder.over !== null}
        />
      )}
    </section>
  );
}

function splitKey(key: string): ["in" | "up", string] {
  const i = key.indexOf(":");
  return [key.slice(0, i) as "in" | "up", key.slice(i + 1)];
}

function TileFace({ button, fallback }: { button: EditorButton; fallback?: string }) {
  const isFolder = button.kind === "folder";
  return (
    <span
      className="deck-key tile__face"
      data-off={!button.enabled || undefined}
      data-folder={isFolder || undefined}
      style={{ [TILE_KEY]: "112px" } as CSSProperties}
    >
      <KeyIcon iconRef={button.iconRef} fallback={isFolder ? "folder" : fallback} className="deck-key__icon" />
      <span className="deck-key__label">{button.label}</span>
      <span className="deck-key__status">{button.enabled ? "" : "Disabled"}</span>
      {isFolder && (
        <svg className="deck-key__folder-mark" viewBox="0 0 24 24" aria-hidden="true">
          <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </span>
  );
}

function TileGhost({ ghost, button, fallback, dropping }: { ghost: DragGhost; button: EditorButton; fallback?: string; dropping: boolean }) {
  return (
    <div
      className="drag-ghost"
      data-dropping={dropping || undefined}
      style={{
        left: ghost.x - ghost.offsetX,
        top: ghost.y - ghost.offsetY,
        width: ghost.width,
        height: ghost.height,
        transformOrigin: `${ghost.offsetX}px ${ghost.offsetY}px`,
      }}
      aria-hidden="true"
    >
      <TileFace button={button} fallback={fallback} />
    </div>
  );
}

export function FolderGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
      <path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" strokeLinejoin="round" />
    </svg>
  );
}

function BackGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path d="M10 6.5 4.5 12l5.5 5.5M4.5 12h15" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
