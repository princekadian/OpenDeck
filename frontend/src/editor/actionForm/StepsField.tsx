// Multi Action step list and Toggle branches. Every step uses the same action
// registry and settings form as a normal button.

import { useEffect, useState } from "react";
import { KeyIcon } from "../../icons/KeyIcon";
import type { EditorTree } from "../api";
import { useReorder } from "../useReorder";
import { ActionFields } from "./ActionFields";
import { ActionPicker } from "./ActionPicker";
import { COMPOSITE_TYPES, defaultConfig } from "./schema";

export interface StepValue {
  actionType: string;
  actionConfig: Record<string, unknown>;
}

const FIRST_STEP = "launch_application";

function newStep(tree: EditorTree, actionType = FIRST_STEP): StepValue {
  return { actionType, actionConfig: defaultConfig(tree.actions.find((a) => a.type === actionType)) };
}

function summary(tree: EditorTree, step: StepValue): string {
  const action = tree.actions.find((a) => a.type === step.actionType);
  const c = step.actionConfig;
  const detail =
    (typeof c.path === "string" && c.path.split("\\").pop()) ||
    (typeof c.url === "string" && c.url) ||
    (typeof c.milliseconds === "number" && `${c.milliseconds} ms`) ||
    (typeof c.volume === "number" && `${c.volume}%`) ||
    (typeof c.text === "string" && `"${c.text.slice(0, 24)}"`) ||
    "";
  return detail ? `${action?.displayName ?? step.actionType}: ${detail}` : (action?.displayName ?? step.actionType);
}

export function StepsField({ id, tree, value, onChange }: { id: string; tree: EditorTree; value: StepValue[]; onChange: (v: StepValue[]) => void }) {
  // Stable ids for list keys and drag reordering, independent of step content.
  const [ids, setIds] = useState(() => value.map((_, i) => `s${i}`));
  const [open, setOpen] = useState<string | null>(value.length ? null : "s0");
  const [counter, setCounter] = useState(value.length);
  const keyed = value.map((step, i) => ({ step, key: ids[i] ?? `s${i}` }));

  const commit = (steps: StepValue[], keys: string[]) => {
    setIds(keys);
    onChange(steps);
  };
  const reorder = useReorder(
    keyed.map((k) => k.key),
    {
      onCommit: (order) => commit(order.map((k) => keyed.find((x) => x.key === k)!.step), order),
    },
  );

  const add = () => {
    const key = `s${counter}`;
    setCounter((c) => c + 1);
    commit([...value, newStep(tree)], [...keyed.map((k) => k.key), key]);
    setOpen(key);
  };
  const remove = (key: string) => {
    const keep = keyed.filter((k) => k.key !== key);
    commit(keep.map((k) => k.step), keep.map((k) => k.key));
  };
  const update = (key: string, step: StepValue) =>
    onChange(keyed.map((k) => (k.key === key ? step : k.step)));

  const byKey = new Map(keyed.map((k) => [k.key, k.step]));
  return (
    <div className="steps" id={id}>
      {value.length > 0 && (
        <ol className="steps__list">
          {reorder.order.map((key, index) => {
            const step = byKey.get(key);
            if (!step) return null;
            const action = tree.actions.find((a) => a.type === step.actionType);
            const binding = reorder.bind(key);
            const expanded = open === key;
            return (
              <li key={key} className="step" ref={binding.ref} data-dragging={binding["data-dragging"]} data-open={expanded || undefined}>
                <div className="step__head" onPointerDown={binding.onPointerDown} onClickCapture={binding.onClickCapture}>
                  <span className="step__handle" aria-hidden="true" title="Drag to reorder">
                    <svg viewBox="0 0 24 24" width="16" height="16"><path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" /></svg>
                  </span>
                  <span className="step__index">{index + 1}</span>
                  <KeyIcon iconRef={null} fallback={action?.icon} className="step__icon" />
                  <button
                    type="button"
                    className="step__title"
                    aria-expanded={expanded}
                    onClick={() => setOpen(expanded ? null : key)}
                    onKeyDown={binding.onKeyDown}
                    title="Alt + arrow keys to reorder"
                  >
                    {summary(tree, step)}
                  </button>
                  <button type="button" className="icon-btn" data-no-drag aria-label={`Remove step ${index + 1}`} onClick={() => remove(key)}>
                    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth={2} strokeLinecap="round" /></svg>
                  </button>
                </div>
                {expanded && (
                  <div className="step__body">
                    <StepEditor id={`${id}-${key}`} tree={tree} step={step} onChange={(s) => update(key, s)} />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
      <button type="button" className="btn btn-sm" onClick={add}>
        + Add action
      </button>
    </div>
  );
}

export function SubActionField({ id, tree, value, onChange }: { id: string; tree: EditorTree; value: StepValue | undefined; onChange: (v: StepValue) => void }) {
  const step = value ?? newStep(tree, "type_text");
  // Store the default that is shown, so saving without changes saves what the user sees.
  useEffect(() => {
    if (value === undefined) onChange(step);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value === undefined]);
  return (
    <div className="sub-action">
      <StepEditor id={id} tree={tree} step={step} onChange={onChange} />
    </div>
  );
}

function StepEditor({ id, tree, step, onChange }: { id: string; tree: EditorTree; step: StepValue; onChange: (s: StepValue) => void }) {
  const action = tree.actions.find((a) => a.type === step.actionType);
  return (
    <>
      <ActionPicker
        id={`${id}-type`}
        tree={tree}
        value={step.actionType}
        exclude={COMPOSITE_TYPES}
        ariaLabel="Action"
        onChange={(actionType) => onChange(newStep(tree, actionType))}
      />
      {action && (
        <div className="sub-action__fields">
          <ActionFields
            tree={tree}
            action={action}
            config={step.actionConfig}
            errors={{}}
            nested
            idPrefix={`${id}-cfg`}
            onChange={(actionConfig) => onChange({ ...step, actionConfig })}
          />
        </div>
      )}
    </>
  );
}
