// Folder helpers for the editor. A folder is a button (kind "folder") whose children
// point at it with parentId; null parentId means "directly on the page".

import type { EditorButton, EditorTree } from "./api";

/** Buttons directly inside one container, in order. */
export function childrenOf(tree: EditorTree, pageId: string, parentId: string | null): EditorButton[] {
  return tree.buttons
    .filter((b) => b.pageId === pageId && (b.parentId ?? null) === parentId)
    .sort((a, b) => a.sortOrder - b.sortOrder);
}

/** Folders from the page down to `folderId`, outermost first. Empty if it is not a folder on that page. */
export function folderPath(tree: EditorTree, pageId: string, folderId: string | null): EditorButton[] {
  const path: EditorButton[] = [];
  const seen = new Set<string>();
  let id = folderId;
  while (id) {
    const folder = tree.buttons.find((b) => b.id === id);
    if (!folder || folder.kind !== "folder" || folder.pageId !== pageId || seen.has(id)) return [];
    seen.add(id);
    path.unshift(folder);
    id = folder.parentId ?? null;
  }
  return path;
}

/** Everything inside a folder, at any depth. */
export function contentsOf(tree: EditorTree, folderId: string): { buttons: number; folders: number } {
  let buttons = 0;
  let folders = 0;
  const queue = [folderId];
  const seen = new Set(queue);
  while (queue.length) {
    const parent = queue.shift()!;
    for (const b of tree.buttons) {
      if ((b.parentId ?? null) !== parent || seen.has(b.id)) continue;
      seen.add(b.id);
      if (b.kind === "folder") {
        folders += 1;
        queue.push(b.id);
      } else {
        buttons += 1;
      }
    }
  }
  return { buttons, folders };
}

/** Ids of a button and everything inside it: places it can't be moved into. */
export function selfAndDescendants(tree: EditorTree, id: string): Set<string> {
  const out = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const b of tree.buttons) {
      if (b.parentId && out.has(b.parentId) && !out.has(b.id)) {
        out.add(b.id);
        grew = true;
      }
    }
  }
  return out;
}

export interface MoveTarget {
  /** Stable key for <select> values. */
  key: string;
  profileName: string;
  pageId: string;
  parentId: string | null;
  label: string;
  depth: number;
}

/** Every page and folder a button can move to, grouped by profile, in tree order. */
export function moveTargets(tree: EditorTree, button: EditorButton): MoveTarget[] {
  const blocked = selfAndDescendants(tree, button.id);
  const out: MoveTarget[] = [];
  const profiles = [...tree.profiles].sort((a, b) => a.sortOrder - b.sortOrder);
  for (const profile of profiles) {
    const pages = tree.pages.filter((p) => p.profileId === profile.id).sort((a, b) => a.sortOrder - b.sortOrder);
    for (const page of pages) {
      out.push({ key: `${page.id}:`, profileName: profile.name, pageId: page.id, parentId: null, label: page.name, depth: 0 });
      const walk = (parentId: string | null, depth: number) => {
        for (const f of childrenOf(tree, page.id, parentId)) {
          if (f.kind !== "folder" || blocked.has(f.id)) continue;
          out.push({ key: `${page.id}:${f.id}`, profileName: profile.name, pageId: page.id, parentId: f.id, label: f.label, depth });
          walk(f.id, depth + 1);
        }
      };
      walk(null, 1);
    }
  }
  return out;
}

export function describeContents({ buttons, folders }: { buttons: number; folders: number }): string {
  const parts = [];
  if (buttons) parts.push(`${buttons} ${buttons === 1 ? "button" : "buttons"}`);
  if (folders) parts.push(`${folders} nested ${folders === 1 ? "folder" : "folders"}`);
  return parts.join(" and ");
}
