import { useState, type CSSProperties } from "react";
import { KeyIcon } from "../icons/KeyIcon";
import { ActionFields } from "./actionForm/ActionFields";
import { ActionPicker } from "./actionForm/ActionPicker";
import { defaultConfig } from "./actionForm/schema";
import { api, ApiError, type ButtonDraft, type ButtonKind, type EditorButton, type EditorTree } from "./api";
import { childrenOf } from "./folders";
import { IconPicker } from "./IconPicker";
import { Modal } from "./Modal";

export type ButtonDialogTarget =
  /** parentId: the folder to create in (null = the page). */
  | { kind: "create"; pageId: string; parentId: string | null; buttonKind: ButtonKind }
  | { kind: "edit"; button: EditorButton };

interface Props {
  tree: EditorTree;
  target: ButtonDialogTarget;
  onClose: () => void;
  /** Called after a successful save with the saved button id. */
  onSaved: (buttonId: string) => void;
  onDelete: (button: EditorButton) => void;
}

const DEFAULT_ACTION = "launch_application";

function initialDraft(target: ButtonDialogTarget, tree: EditorTree): ButtonDraft {
  if (target.kind === "edit") {
    const { kind, label, description, iconRef, actionType, actionConfig, enabled } = target.button;
    return { kind, label, description, iconRef, actionType, actionConfig: { ...actionConfig }, enabled };
  }
  const action = tree.actions.find((a) => a.type === DEFAULT_ACTION);
  return {
    kind: target.buttonKind,
    label: "",
    description: "",
    iconRef: null,
    actionType: DEFAULT_ACTION,
    actionConfig: defaultConfig(action),
    enabled: true,
  };
}

export function ButtonDialog({ tree, target, onClose, onSaved, onDelete }: Props) {
  const [draft, setDraft] = useState<ButtonDraft>(() => initialDraft(target, tree));
  const [initial] = useState(() => JSON.stringify(initialDraft(target, tree)));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);
  // Name and icon read from a picked application; used for auto-fill and "Use application icon".
  const [appInfo, setAppInfo] = useState<{ name: string; iconRef: string | null } | null>(null);

  const pageId = target.kind === "edit" ? target.button.pageId : target.pageId;
  const parentId = target.kind === "edit" ? (target.button.parentId ?? null) : target.parentId;
  const siblings = childrenOf(tree, pageId, parentId);
  // A folder that still holds buttons can't turn into an action (they would be lost).
  const folderHasContents = target.kind === "edit" && target.button.kind === "folder" && childrenOf(tree, pageId, target.button.id).length > 0;
  const [position, setPosition] = useState(() =>
    target.kind === "edit" ? siblings.findIndex((b) => b.id === target.button.id) : siblings.length,
  );
  const positionCount = target.kind === "edit" ? siblings.length : siblings.length + 1;

  const isFolder = draft.kind === "folder";
  const action = isFolder ? undefined : tree.actions.find((a) => a.type === draft.actionType);
  const dirty = JSON.stringify(draft) !== initial;

  const set = (patch: Partial<ButtonDraft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setTest(null);
  };

  async function onPathPicked(path: string) {
    try {
      const info = await api.appInfo(path);
      setAppInfo(info);
      setDraft((d) => ({
        ...d,
        // Fill only what the user has not chosen themselves.
        label: d.label.trim() === "" || d.label === appInfo?.name ? info.name : d.label,
        iconRef: d.iconRef === null || d.iconRef === appInfo?.iconRef ? (info.iconRef ?? d.iconRef) : d.iconRef,
      }));
    } catch {
      /* name/icon are conveniences; the path itself is already set */
    }
  }

  async function runTest() {
    if (action?.destructive && !confirm(`"${action.displayName}" will really run on this PC now. Continue?`)) return;
    setTesting(true);
    setTest(null);
    try {
      const result = await api.testAction(draft.actionType, draft.actionConfig);
      setTest(result.success ? { ok: true, text: "Worked on this PC." } : { ok: false, text: result.error?.message ?? "Failed." });
    } catch (e) {
      setTest({ ok: false, text: e instanceof ApiError ? e.message : "Test failed." });
    } finally {
      setTesting(false);
    }
  }

  async function save() {
    if (saving) return;
    setSaving(true);
    setErrors({});
    setFormError(null);
    try {
      const saved =
        target.kind === "edit" ? await api.updateButton(target.button.id, draft) : await api.createButton(pageId, draft, parentId);
      const currentIds = target.kind === "edit" ? siblings.map((b) => b.id) : [...siblings.map((b) => b.id), saved.id];
      const from = currentIds.indexOf(saved.id);
      if (from !== position) {
        currentIds.splice(from, 1);
        currentIds.splice(position, 0, saved.id);
        await api.reorderButtons(pageId, currentIds, parentId);
      }
      onSaved(saved.id);
      onClose();
    } catch (e) {
      if (e instanceof ApiError) {
        setErrors(mapFieldErrors(e.fields));
        setFormError(e.message);
      } else {
        setFormError("Couldn't save. Try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  const noun = isFolder ? "folder" : "button";
  const title = target.kind === "edit" ? `Edit ${noun}` : `New ${noun}`;
  const previewLabel = draft.label.trim() || (isFolder ? "Folder" : action?.displayName) || "Button";
  const discard = `Discard changes to this ${noun}?`;

  return (
    <Modal
      title={title}
      wide
      onClose={onClose}
      onSubmit={save}
      canClose={() => !dirty || confirm(discard)}
      footer={
        <>
          {target.kind === "edit" && (
            <button type="button" className="btn btn-quiet-danger modal__foot-start" onClick={() => onDelete(target.button)}>
              Delete
            </button>
          )}
          <button type="button" className="btn" onClick={() => (!dirty || confirm(discard)) && onClose()}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? "Saving…" : target.kind === "edit" ? "Save" : isFolder ? "Create folder" : "Add button"}
          </button>
        </>
      }
    >
      <div className="button-editor">
        <aside className="button-editor__preview" aria-label="Preview">
          <div
            className="deck-key key-preview"
            style={{ "--key": "148px" } as CSSProperties}
            data-off={!draft.enabled || undefined}
            data-folder={isFolder || undefined}
          >
            <KeyIcon iconRef={draft.iconRef} fallback={isFolder ? "folder" : action?.icon} className="deck-key__icon" />
            <span className="deck-key__label">{previewLabel}</span>
            <span className="deck-key__status">{draft.enabled ? "" : "Disabled"}</span>
            {isFolder && (
              <svg className="deck-key__folder-mark" viewBox="0 0 24 24" aria-hidden="true">
                <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </div>
          {isFolder ? (
            <p className="field__hint">Pressing a folder on a device opens its buttons. It never runs anything on this PC.</p>
          ) : (
            <button type="button" className="btn btn-sm" onClick={runTest} disabled={testing || !action}>
              {testing ? "Testing…" : "Test on this PC"}
            </button>
          )}
          {test && (
            <p className={test.ok ? "test-result" : "test-result test-result--error"} role="status">
              {test.text}
            </p>
          )}
        </aside>

        <div className="button-editor__props">
          {formError && (
            <p className="form-error" role="alert">
              {formError}
            </p>
          )}

          <fieldset className="kind-switch">
            <legend className="field__label">Button type</legend>
            <div className="kind-switch__options" role="radiogroup">
              {(["action", "folder"] as const).map((kind) => (
                <label key={kind} className="kind-switch__option" data-checked={draft.kind === kind || undefined}>
                  <input
                    type="radio"
                    name="button-kind"
                    value={kind}
                    checked={draft.kind === kind}
                    disabled={kind === "action" && folderHasContents}
                    onChange={() => set({ kind })}
                  />
                  <span className="kind-switch__name">{kind === "action" ? "Action" : "Folder"}</span>
                  <span className="kind-switch__hint">{kind === "action" ? "Runs something on this PC" : "Opens more buttons"}</span>
                </label>
              ))}
            </div>
            {folderHasContents && <p className="field__hint">Move or delete the buttons inside to turn this folder into an action.</p>}
          </fieldset>

          {!isFolder && (
          <section className="prop-section" aria-labelledby="sec-action">
            <h3 id="sec-action" className="prop-section__title">
              Action
            </h3>
            <div className="field">
              <label className="field__label" htmlFor="action-type">
                When pressed
              </label>
              <ActionPicker
                id="action-type"
                tree={tree}
                value={draft.actionType}
                onChange={(actionType) => {
                  setAppInfo(null);
                  set({ actionType, actionConfig: defaultConfig(tree.actions.find((a) => a.type === actionType)) });
                }}
              />
              {action && <p className="field__hint">{action.description}</p>}
            </div>
            {action && (
              <ActionFields
                tree={tree}
                action={action}
                config={draft.actionConfig}
                errors={errors}
                onChange={(actionConfig) => set({ actionConfig })}
                onPathPicked={onPathPicked}
              />
            )}
          </section>
          )}

          <section className="prop-section" aria-labelledby="sec-look">
            <h3 id="sec-look" className="prop-section__title">
              Appearance
            </h3>
            <div className="field">
              <label className="field__label" htmlFor="btn-label">
                Name
              </label>
              <input
                id="btn-label"
                className="input"
                value={draft.label}
                maxLength={40}
                placeholder={isFolder ? "Folder name" : action?.displayName}
                onChange={(e) => set({ label: e.target.value })}
                aria-invalid={errors.label ? true : undefined}
              />
              {errors.label && <p className="field__error">{errors.label}</p>}
            </div>
            <div className="field">
              <span className="field__label">Icon</span>
              <IconPicker
                value={draft.iconRef}
                fallback={isFolder ? "folder" : (action?.icon ?? null)}
                defaultCaption={isFolder ? "Default folder icon" : undefined}
                appIconRef={appInfo?.iconRef ?? null}
                onChange={(iconRef) => set({ iconRef })}
              />
              {errors.iconRef && <p className="field__error">{errors.iconRef}</p>}
            </div>
          </section>

          <section className="prop-section" aria-labelledby="sec-more">
            <h3 id="sec-more" className="prop-section__title">
              Details
            </h3>
            <div className="field">
              <label className="field__label" htmlFor="btn-desc">
                Description <span className="field__optional">(optional)</span>
              </label>
              <input
                id="btn-desc"
                className="input"
                value={draft.description}
                maxLength={200}
                placeholder="A note for yourself"
                onChange={(e) => set({ description: e.target.value })}
              />
            </div>
            <div className="field-row">
              <div className="field">
                <label className="field__label" htmlFor="btn-position">
                  Position
                </label>
                <select
                  id="btn-position"
                  className="input input-narrow"
                  value={position}
                  onChange={(e) => setPosition(Number(e.target.value))}
                >
                  {Array.from({ length: positionCount }, (_, i) => (
                    <option key={i} value={i}>
                      {i + 1} of {positionCount}
                    </option>
                  ))}
                </select>
              </div>
              <label className="switch-row">
                <input type="checkbox" className="switch" checked={draft.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
                <span>Enabled</span>
              </label>
            </div>
          </section>
        </div>
      </div>
    </Modal>
  );
}

/** The server keys errors by top-level setting ("url", "steps", "shortcut"). */
function mapFieldErrors(fields: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, message] of Object.entries(fields)) out[path.split(".")[0]] = message;
  return out;
}
