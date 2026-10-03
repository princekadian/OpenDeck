// Editor mode: configure profiles, pages and buttons. Runs on the PC (localhost only).

import { useCallback, useEffect, useRef, useState } from "react";
import { PRODUCT_NAME } from "../branding";
import { HostPage } from "../host/HostPage";
import { ObsPanel } from "./ObsPanel";
import { api, ApiError, type EditorButton, type EditorPage, type EditorProfile, type EditorTree } from "./api";
import { ButtonDialog, type ButtonDialogTarget } from "./ButtonDialog";
import { Menu, type MenuItem, type MenuRequest } from "./Menu";
import { contentsOf, describeContents, folderPath, moveTargets } from "./folders";
import { ConfirmDialog, PromptDialog } from "./Modal";
import { MonitorCanvas } from "./MonitorCanvas";
import { PageCanvas } from "./PageCanvas";
import { Sidebar, type EditorView } from "./Sidebar";
import "./editor.css";

const VIEW_KEY = "msd.editor.view.v1";

type Overlay =
  | { kind: "button"; target: ButtonDialogTarget }
  | { kind: "prompt"; title: string; label: string; initial: string; confirmLabel: string; submit: (v: string) => Promise<void> }
  | { kind: "confirm"; title: string; message: string; confirmLabel: string; run: () => Promise<void> }
  | { kind: "move"; button: EditorButton };

/** `embedded`: inside the desktop app, which has its own navigation, Devices and Integrations. */
export function EditorApp({ initialView, embedded = false }: { initialView?: "devices"; embedded?: boolean }) {
  const [tree, setTree] = useState<EditorTree | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [view, setView] = useState<EditorView | null>(() => (initialView === "devices" ? { kind: "devices" } : loadView()));
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [menu, setMenu] = useState<MenuRequest | null>(null);
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const notify = useCallback((text: string, error = false) => {
    clearTimeout(toastTimer.current);
    setToast({ text, error });
    toastTimer.current = setTimeout(() => setToast(null), error ? 6000 : 2500);
  }, []);

  const reload = useCallback(async () => {
    try {
      const next = await api.tree();
      setTree(next);
      setLoadError(null);
      setView((v) => validView(next, v));
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Couldn't load the configuration.");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (view?.kind === "page") saveView(view);
  }, [view]);

  /** Run a change, report problems, then refresh from the PC (the source of truth). */
  const run = useCallback(
    async (change: () => Promise<unknown>, success?: string) => {
      try {
        await change();
        if (success) notify(success);
      } catch (e) {
        notify(e instanceof ApiError ? e.message : "That didn't work. Try again.", true);
      } finally {
        await reload();
      }
    },
    [notify, reload],
  );

  if (loadError && !tree) {
    return (
      <div className="editor editor--message">
        <p role="alert">{loadError}</p>
        <button type="button" className="btn" onClick={() => void reload()}>
          Try again
        </button>
      </div>
    );
  }
  if (!tree) return <div className="editor editor--message" aria-busy="true" />;

  const profile = view?.kind === "page" ? tree.profiles.find((p) => p.id === view.profileId) : undefined;
  const page = view?.kind === "page" ? tree.pages.find((p) => p.id === view.pageId) : undefined;
  const folderId = view?.kind === "page" ? (view.folderId ?? null) : null;
  const openFolder = (id: string | null) => {
    if (view?.kind === "page") setView({ ...view, folderId: id });
  };

  // ---- menus ---------------------------------------------------------------

  const profileMenu = (p: EditorProfile): MenuItem[] => [
    { label: "Rename…", onSelect: () => promptRename("Rename profile", p.name, (name) => api.updateProfile(p, name)) },
    { label: "Duplicate", onSelect: () => void run(() => api.duplicateProfile(p.id), "Profile duplicated") },
    {
      label: "Add System Monitoring page",
      onSelect: () =>
        void run(async () => {
          const pg = await api.createPage(p.id, "System Monitoring", "monitor");
          setView({ kind: "page", profileId: p.id, pageId: pg.id });
        }, "System Monitoring page added"),
    },
    {
      label: "Show first on devices",
      disabled: tree.activeProfileId === p.id,
      onSelect: () => void run(() => api.setActiveProfile(p.id), `Devices now open ${p.name}`),
    },
    {
      label: "Delete…",
      danger: true,
      separatorBefore: true,
      disabled: tree.profiles.length <= 1,
      onSelect: () =>
        setOverlay({
          kind: "confirm",
          title: "Delete profile?",
          message: `"${p.name}" and all of its pages and buttons will be deleted. This can't be undone.`,
          confirmLabel: "Delete profile",
          run: () => run(() => api.deleteProfile(p.id), "Profile deleted"),
        }),
    },
  ];

  const pageMenu = (pg: EditorPage): MenuItem[] => [
    { label: "Rename…", onSelect: () => promptRename("Rename page", pg.name, (name) => api.updatePage(pg, name)) },
    {
      label: "Duplicate",
      onSelect: () =>
        void run(async () => {
          const copy = await api.duplicatePage(pg.id);
          setView({ kind: "page", profileId: copy.profileId, pageId: copy.id });
        }, "Page duplicated"),
    },
    {
      label: "Delete…",
      danger: true,
      separatorBefore: true,
      disabled: tree.pages.filter((x) => x.profileId === pg.profileId).length <= 1,
      onSelect: () =>
        setOverlay({
          kind: "confirm",
          title: "Delete page?",
          message: `"${pg.name}" and its ${countButtons(tree, pg.id)} buttons will be deleted. This can't be undone.`,
          confirmLabel: "Delete page",
          run: () => run(() => api.deletePage(pg.id), "Page deleted"),
        }),
    },
  ];

  const buttonMenu = (b: EditorButton): MenuItem[] => {
    const noun = b.kind === "folder" ? "Folder" : "Button";
    const edit = () => setOverlay({ kind: "button", target: { kind: "edit", button: b } });
    return [
      ...(b.kind === "folder" && b.id !== folderId ? [{ label: "Open", onSelect: () => openFolder(b.id) }] : []),
      { label: b.kind === "folder" ? "Rename or change icon…" : "Edit…", onSelect: edit },
      { label: "Duplicate", onSelect: () => void run(() => api.duplicateButton(b.id), `${noun} duplicated`) },
      { label: "Move to…", onSelect: () => setOverlay({ kind: "move", button: b }) },
      ...(b.kind === "folder" ? [] : [{ label: "Change icon…", onSelect: edit }]),
      {
        label: b.enabled ? "Disable" : "Enable",
        onSelect: () => void run(() => api.setButtonEnabled(b.id, !b.enabled), b.enabled ? `${noun} disabled` : `${noun} enabled`),
      },
      { label: "Delete…", danger: true, separatorBefore: true, onSelect: () => confirmDeleteButton(b) },
    ];
  };

  function promptRename(title: string, current: string, save: (name: string) => Promise<unknown>) {
    setOverlay({
      kind: "prompt",
      title,
      label: "Name",
      initial: current,
      confirmLabel: "Rename",
      submit: async (name) => {
        await save(name);
        await reload();
      },
    });
  }

  function confirmDeleteButton(b: EditorButton) {
    if (b.kind === "folder") {
      const inside = describeContents(contentsOf(tree!, b.id));
      setOverlay({
        kind: "confirm",
        title: `Delete "${b.label}"?`,
        message: inside
          ? `This folder contains ${inside}. The folder and everything inside it will be deleted from every device. This can't be undone.`
          : "This empty folder will be removed from every device.",
        confirmLabel: inside ? "Delete folder and contents" : "Delete folder",
        run: () => run(() => api.deleteButton(b.id), "Folder deleted"),
      });
      return;
    }
    setOverlay({
      kind: "confirm",
      title: "Delete button?",
      message: `"${b.label || "Untitled"}" will be removed from every device.`,
      confirmLabel: "Delete button",
      run: () => run(() => api.deleteButton(b.id), "Button deleted"),
    });
  }

  function containerName(pageId: string, parentId: string | null): string {
    if (parentId) return tree!.buttons.find((b) => b.id === parentId)?.label ?? "the folder";
    return tree!.pages.find((p) => p.id === pageId)?.name ?? "the page";
  }

  // ---- render --------------------------------------------------------------

  return (
    <div className={embedded ? "editor editor--embedded" : "editor"}>
      {!embedded && (
      <header className="editor__bar">
        <span className="editor__brand">{PRODUCT_NAME}</span>
        <span className="editor__mode">Editor</span>
        <span className="editor__bar-spacer" />
        <span className="editor__live" title="Changes appear on connected devices immediately">
          <span className="led" data-tone="online" aria-hidden="true" /> Changes save automatically
        </span>
      </header>
      )}

      <div className="editor__body">
        <Sidebar
          tree={tree}
          view={view}
          onSelectProfile={(profileId) => {
            const first = tree.pages.filter((p) => p.profileId === profileId).sort((a, b) => a.sortOrder - b.sortOrder)[0];
            if (first) setView({ kind: "page", profileId, pageId: first.id });
          }}
          onSelectPage={(profileId, pageId, folder = null) => setView({ kind: "page", profileId, pageId, folderId: folder })}
          onShowDevices={() => setView({ kind: "devices" })}
          onShowIntegrations={() => setView({ kind: "integrations" })}
          onAddProfile={() =>
            setOverlay({
              kind: "prompt",
              title: "New profile",
              label: "Profile name",
              initial: "",
              confirmLabel: "Create profile",
              submit: async (name) => {
                const p = await api.createProfile(name);
                const next = await api.tree();
                setTree(next);
                const first = next.pages.find((pg) => pg.profileId === p.id);
                if (first) setView({ kind: "page", profileId: p.id, pageId: first.id });
              },
            })
          }
          onAddPage={(profileId) =>
            setOverlay({
              kind: "prompt",
              title: "New page",
              label: "Page name",
              initial: "",
              confirmLabel: "Create page",
              submit: async (name) => {
                const pg = await api.createPage(profileId, name);
                await reload();
                setView({ kind: "page", profileId, pageId: pg.id });
              },
            })
          }
          onReorderProfiles={(ids) => void run(() => api.reorderProfiles(ids))}
          onReorderPages={(profileId, ids) => void run(() => api.reorderPages(profileId, ids))}
          profileMenu={profileMenu}
          pageMenu={pageMenu}
          openMenu={setMenu}
          showFooter={!embedded}
        />

        <main className="editor__main">
          {view?.kind === "devices" && <HostPage />}
          {view?.kind === "integrations" && <ObsPanel />}
          {view?.kind === "page" && profile && page?.kind === "monitor" && (
            <MonitorCanvas
              key={page.id}
              profile={profile}
              page={page}
              onSelectProfile={(profileId) => {
                const first = tree.pages.filter((p) => p.profileId === profileId).sort((a, b) => a.sortOrder - b.sortOrder)[0];
                if (first) setView({ kind: "page", profileId, pageId: first.id });
              }}
              pageMenu={pageMenu}
              openMenu={setMenu}
              notify={notify}
            />
          )}
          {view?.kind === "page" && profile && page && page.kind !== "monitor" && (
            <PageCanvas
              tree={tree}
              profile={profile}
              page={page}
              folderId={folderId}
              onOpenFolder={openFolder}
              onSelectProfile={(profileId) => {
                const first = tree.pages.filter((p) => p.profileId === profileId).sort((a, b) => a.sortOrder - b.sortOrder)[0];
                if (first) setView({ kind: "page", profileId, pageId: first.id });
              }}
              onAdd={(buttonKind) =>
                setOverlay({ kind: "button", target: { kind: "create", pageId: page.id, parentId: folderId, buttonKind } })
              }
              onEditButton={(b) => setOverlay({ kind: "button", target: { kind: "edit", button: b } })}
              onReorder={(ids) => void run(() => api.reorderButtons(page.id, ids, folderId))}
              onMoveInto={(b, parentId) =>
                void run(() => api.moveButton(b.id, b.pageId, parentId), `Moved to ${containerName(b.pageId, parentId)}`)
              }
              buttonMenu={buttonMenu}
              pageMenu={pageMenu}
              openMenu={setMenu}
            />
          )}
        </main>
      </div>

      {menu && <Menu request={menu} onClose={() => setMenu(null)} />}

      {overlay?.kind === "button" && (
        <ButtonDialog
          tree={tree}
          target={overlay.target}
          onClose={() => setOverlay(null)}
          onSaved={() => {
            const t = overlay.target;
            const folder = t.kind === "edit" ? t.button.kind === "folder" : t.buttonKind === "folder";
            notify(t.kind === "edit" ? (folder ? "Folder saved" : "Button saved") : folder ? "Folder created" : "Button added");
            void reload();
          }}
          onDelete={(b) => confirmDeleteButton(b)}
        />
      )}
      {overlay?.kind === "prompt" && (
        <PromptDialog
          title={overlay.title}
          label={overlay.label}
          initial={overlay.initial}
          confirmLabel={overlay.confirmLabel}
          onClose={() => setOverlay(null)}
          onSubmit={async (value) => {
            try {
              await overlay.submit(value);
            } catch (e) {
              return e instanceof ApiError ? (Object.values(e.fields)[0] ?? e.message) : "That didn't work.";
            }
          }}
        />
      )}
      {overlay?.kind === "confirm" && (
        <ConfirmDialog
          title={overlay.title}
          message={overlay.message}
          confirmLabel={overlay.confirmLabel}
          danger
          onClose={() => setOverlay(null)}
          onConfirm={() => void overlay.run()}
        />
      )}
      {overlay?.kind === "move" && (
        <MoveDialog
          tree={tree}
          button={overlay.button}
          onClose={() => setOverlay(null)}
          onMove={(pageId, parentId) =>
            void run(() => api.moveButton(overlay.button.id, pageId, parentId), `Moved to ${containerName(pageId, parentId)}`)
          }
        />
      )}

      <div className="toast" role="status" aria-live="polite" data-visible={toast ? "" : undefined} data-error={toast?.error || undefined}>
        {toast?.text}
      </div>
    </div>
  );
}

function MoveDialog({
  tree,
  button,
  onClose,
  onMove,
}: {
  tree: EditorTree;
  button: EditorButton;
  onClose: () => void;
  onMove: (pageId: string, parentId: string | null) => void;
}) {
  const here = `${button.pageId}:${button.parentId ?? ""}`;
  const options = moveTargets(tree, button);
  const [target, setTarget] = useState(options.find((o) => o.key !== here)?.key ?? "");
  const chosen = options.find((o) => o.key === target);
  const noun = button.kind === "folder" ? "folder" : "button";
  return (
    <ConfirmDialog
      title={`Move ${noun}`}
      onClose={onClose}
      confirmLabel="Move"
      disabled={!chosen || target === here}
      onConfirm={() => chosen && onMove(chosen.pageId, chosen.parentId)}
    >
      {options.length <= 1 ? (
        <p className="modal__text">Create another page or folder first.</p>
      ) : (
        <div className="field">
          <label className="field__label" htmlFor="move-target">
            Move "{button.label || "Untitled"}" to
          </label>
          <select id="move-target" className="input" value={target} onChange={(e) => setTarget(e.target.value)}>
            {Object.entries(groupBy(options, (o) => o.profileName)).map(([profile, items]) => (
              <optgroup key={profile} label={profile}>
                {items.map((o) => (
                  <option key={o.key} value={o.key} disabled={o.key === here}>
                    {"\u2003".repeat(o.depth)}
                    {o.depth ? "\u25B8 " : ""}
                    {o.label}
                    {o.key === here ? " (current)" : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {button.kind === "folder" && <p className="field__hint">Everything inside the folder moves with it.</p>}
        </div>
      )}
    </ConfirmDialog>
  );
}

function groupBy<T>(items: T[], key: (t: T) => string): Record<string, T[]> {
  const out: Record<string, T[]> = {};
  for (const item of items) (out[key(item)] ??= []).push(item);
  return out;
}

function countButtons(tree: EditorTree, pageId: string): number {
  return tree.buttons.filter((b) => b.pageId === pageId).length;
}

function validView(tree: EditorTree, view: EditorView | null): EditorView | null {
  if (view?.kind === "devices" || view?.kind === "integrations") return view;
  if (view?.kind === "page" && tree.pages.some((p) => p.id === view.pageId && p.profileId === view.profileId)) {
    // A deleted or moved folder drops the editor back to the page.
    if (view.folderId && folderPath(tree, view.pageId, view.folderId).length === 0) return { ...view, folderId: null };
    return view;
  }
  const profileId =
    (view?.kind === "page" && tree.profiles.some((p) => p.id === view.profileId) ? view.profileId : null) ??
    tree.activeProfileId ??
    tree.profiles[0]?.id;
  const page = tree.pages.filter((p) => p.profileId === profileId).sort((a, b) => a.sortOrder - b.sortOrder)[0];
  return page ? { kind: "page", profileId: page.profileId, pageId: page.id } : null;
}

function loadView(): EditorView | null {
  try {
    return JSON.parse(localStorage.getItem(VIEW_KEY) ?? "null");
  } catch {
    return null;
  }
}

function saveView(view: EditorView): void {
  try {
    localStorage.setItem(VIEW_KEY, JSON.stringify(view));
  } catch {
    /* not remembered */
  }
}
