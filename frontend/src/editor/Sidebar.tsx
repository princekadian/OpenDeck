import type { MouseEvent } from "react";
import type { EditorPage, EditorProfile, EditorTree } from "./api";
import { childrenOf, folderPath } from "./folders";
import { menuAt, type MenuItem, type MenuRequest } from "./Menu";
import { useReorder } from "./useReorder";

export type EditorView =
  /** folderId: the folder open in the canvas; null/absent = the page itself. */
  | { kind: "page"; profileId: string; pageId: string; folderId?: string | null }
  | { kind: "devices" }
  | { kind: "integrations" };

interface Props {
  tree: EditorTree;
  view: EditorView | null;
  onSelectPage: (profileId: string, pageId: string, folderId?: string | null) => void;
  onSelectProfile: (profileId: string) => void;
  onShowDevices: () => void;
  onShowIntegrations: () => void;
  onAddProfile: () => void;
  onAddPage: (profileId: string) => void;
  onReorderProfiles: (ids: string[]) => void;
  onReorderPages: (profileId: string, ids: string[]) => void;
  profileMenu: (profile: EditorProfile) => MenuItem[];
  pageMenu: (page: EditorPage) => MenuItem[];
  openMenu: (request: MenuRequest) => void;
  /** Connect devices / Integrations links (the desktop app has its own navigation for these). */
  showFooter?: boolean;
}

export function Sidebar(props: Props) {
  const { tree, view, onSelectProfile, onAddProfile, onReorderProfiles, profileMenu, openMenu } = props;
  const profiles = [...tree.profiles].sort((a, b) => a.sortOrder - b.sortOrder);
  const selectedProfileId = view?.kind === "page" ? view.profileId : null;
  const reorder = useReorder(
    profiles.map((p) => p.id),
    {
      onCommit: onReorderProfiles,
      onLongPress: (id, x, y) => {
        const p = profiles.find((x) => x.id === id);
        if (p) openMenu({ x, y, items: profileMenu(p) });
      },
    },
  );
  const byId = new Map(profiles.map((p) => [p.id, p]));

  return (
    <nav className="sidebar" aria-label="Profiles and pages">
      <div className="sidebar__head">
        <h2 className="sidebar__title">Profiles</h2>
        <button type="button" className="icon-btn" onClick={onAddProfile} aria-label="New profile" title="New profile">
          <PlusIcon />
        </button>
      </div>

      <ul className="tree" role="list">
        {reorder.order.map((id) => {
          const profile = byId.get(id);
          if (!profile) return null;
          const expanded = profile.id === selectedProfileId;
          const binding = reorder.bind(profile.id);
          const contextMenu = (e: MouseEvent) => {
            e.preventDefault();
            openMenu({ x: e.clientX, y: e.clientY, items: profileMenu(profile) });
          };
          return (
            <li key={profile.id} className="tree__group" data-expanded={expanded || undefined}>
              <div
                className="tree__row tree__row--profile"
                ref={binding.ref}
                data-dragging={binding["data-dragging"]}
                data-selected={expanded || undefined}
                onPointerDown={binding.onPointerDown}
                onClickCapture={binding.onClickCapture}
                onContextMenu={contextMenu}
              >
                <button
                  type="button"
                  className="tree__main"
                  aria-expanded={expanded}
                  aria-label={tree.activeProfileId === profile.id ? `${profile.name}, shown first on devices` : profile.name}
                  onClick={() => onSelectProfile(profile.id)}
                  onKeyDown={binding.onKeyDown}
                  title="Alt + arrow keys to reorder"
                >
                  <ChevronIcon open={expanded} />
                  <span className="tree__name">{profile.name}</span>
                  {tree.activeProfileId === profile.id && <span className="badge">Default</span>}
                </button>
                <MoreButton
                  label={`${profile.name} options`}
                  onOpen={(el) => openMenu({ ...menuAt(el), items: profileMenu(profile), returnFocus: el })}
                />
              </div>
              {expanded && <PageList {...props} profile={profile} />}
            </li>
          );
        })}
      </ul>
      {reorder.ghost && <DragGhost ghost={reorder.ghost} label={byId.get(reorder.ghost.id)?.name ?? ""} />}

      {props.showFooter !== false && (
      <div className="sidebar__foot">
        <button
          type="button"
          className="tree__row tree__main sidebar__devices"
          data-selected={view?.kind === "devices" || undefined}
          onClick={props.onShowDevices}
        >
          <DevicesIcon />
          <span className="tree__name">Connect devices</span>
        </button>
        <button
          type="button"
          className="tree__row tree__main sidebar__devices"
          data-selected={view?.kind === "integrations" || undefined}
          onClick={props.onShowIntegrations}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
            <path d="M9 3v4M15 3v4M6.5 7h11v4a5.5 5.5 0 0 1-11 0Z" />
            <path d="M12 16.5V21" strokeLinecap="round" />
          </svg>
          <span className="tree__name">Integrations</span>
        </button>
      </div>
      )}
    </nav>
  );
}

function PageList({ tree, view, profile, onSelectPage, onAddPage, onReorderPages, pageMenu, openMenu }: Props & { profile: EditorProfile }) {
  const pages = tree.pages.filter((p) => p.profileId === profile.id).sort((a, b) => a.sortOrder - b.sortOrder);
  const counts = new Map<string, number>();
  for (const b of tree.buttons) if (b.kind !== "folder") counts.set(b.pageId, (counts.get(b.pageId) ?? 0) + 1);
  const reorder = useReorder(
    pages.map((p) => p.id),
    {
      onCommit: (ids) => onReorderPages(profile.id, ids),
      onLongPress: (id, x, y) => {
        const p = pages.find((x) => x.id === id);
        if (p) openMenu({ x, y, items: pageMenu(p) });
      },
    },
  );
  const byId = new Map(pages.map((p) => [p.id, p]));

  return (
    <ul className="tree__pages" role="list">
      {reorder.order.map((id) => {
        const page = byId.get(id);
        if (!page) return null;
        const selected = view?.kind === "page" && view.pageId === page.id;
        const openFolder = selected ? (view.folderId ?? null) : null;
        const binding = reorder.bind(page.id);
        return (
          <li key={page.id}>
            <div
              className="tree__row tree__row--page"
              ref={binding.ref}
              data-dragging={binding["data-dragging"]}
              data-selected={selected || undefined}
              onPointerDown={binding.onPointerDown}
              onClickCapture={binding.onClickCapture}
              onContextMenu={(e) => {
                e.preventDefault();
                openMenu({ x: e.clientX, y: e.clientY, items: pageMenu(page) });
              }}
            >
              <button
                type="button"
                className="tree__main"
                aria-current={selected && !openFolder ? "page" : undefined}
                aria-label={page.kind === "monitor" ? `${page.name}, system monitoring` : `${page.name}, ${counts.get(page.id) ?? 0} buttons`}
                onClick={() => onSelectPage(profile.id, page.id)}
                onKeyDown={binding.onKeyDown}
                title="Alt + arrow keys to reorder"
              >
                {page.kind === "monitor" && (
                  <svg className="tree__kind" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M3 12h4l2.5-6 5 12 2.5-6h4" />
                  </svg>
                )}
                <span className="tree__name">{page.name}</span>
                {page.kind !== "monitor" && (
                  <span className="tree__count" aria-hidden="true">
                    {counts.get(page.id) ?? 0}
                  </span>
                )}
              </button>
              <MoreButton
                label={`${page.name} options`}
                onOpen={(el) => openMenu({ ...menuAt(el), items: pageMenu(page), returnFocus: el })}
              />
            </div>
            {selected && (
              <FolderList
                tree={tree}
                pageId={page.id}
                parentId={null}
                openPath={folderPath(tree, page.id, openFolder).map((f) => f.id)}
                onOpen={(folderId) => onSelectPage(profile.id, page.id, folderId)}
              />
            )}
          </li>
        );
      })}
      <li>
        <button type="button" className="tree__add" onClick={() => onAddPage(profile.id)}>
          <PlusIcon /> Add page
        </button>
      </li>
      {reorder.ghost && <DragGhost ghost={reorder.ghost} label={byId.get(reorder.ghost.id)?.name ?? ""} />}
    </ul>
  );
}

/** Folders of the selected page. Only the open folder's branch is expanded. */
function FolderList({
  tree,
  pageId,
  parentId,
  openPath,
  onOpen,
}: {
  tree: EditorTree;
  pageId: string;
  parentId: string | null;
  openPath: string[];
  onOpen: (folderId: string) => void;
}) {
  const folders = childrenOf(tree, pageId, parentId).filter((b) => b.kind === "folder");
  if (!folders.length) return null;
  return (
    <ul className="tree__folders" role="list">
      {folders.map((f) => {
        const current = openPath.at(-1) === f.id;
        return (
          <li key={f.id}>
            <button
              type="button"
              className="tree__row tree__main tree__folder"
              data-selected={current || undefined}
              aria-current={current ? "location" : undefined}
              onClick={() => onOpen(f.id)}
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
                <path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" strokeLinejoin="round" />
              </svg>
              <span className="tree__name">{f.label}</span>
            </button>
            {openPath.includes(f.id) && <FolderList tree={tree} pageId={pageId} parentId={f.id} openPath={openPath} onOpen={onOpen} />}
          </li>
        );
      })}
    </ul>
  );
}

export function MoreButton({ label, onOpen }: { label: string; onOpen: (el: HTMLElement) => void }) {
  return (
    <button
      type="button"
      className="icon-btn more-btn"
      data-no-drag
      aria-label={label}
      aria-haspopup="menu"
      onClick={(e) => onOpen(e.currentTarget)}
    >
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <circle cx="6" cy="12" r="1.6" fill="currentColor" />
        <circle cx="12" cy="12" r="1.6" fill="currentColor" />
        <circle cx="18" cy="12" r="1.6" fill="currentColor" />
      </svg>
    </button>
  );
}

function DragGhost({ ghost, label }: { ghost: NonNullable<ReturnType<typeof useReorder>["ghost"]>; label: string }) {
  return (
    <div
      className="drag-ghost drag-ghost--row"
      style={{ left: ghost.x - ghost.offsetX, top: ghost.y - ghost.offsetY, width: ghost.width, height: ghost.height }}
      aria-hidden="true"
    >
      {label}
    </div>
  );
}

export function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
    </svg>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg className="tree__chevron" data-open={open || undefined} viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DevicesIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
      <rect x="3" y="5" width="12" height="9" rx="1.5" />
      <rect x="15" y="8" width="6" height="11" rx="1.5" />
      <path d="M6 18h6" strokeLinecap="round" />
    </svg>
  );
}
