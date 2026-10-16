// Settings form generated from the selected action's JSON schema.
// New actions (and future plugins) get a form without editor changes: the field
// type and the schema's `widget` hint choose the control. Only relevant fields show.

import { useState } from "react";
import { api, ApiError, type ActionInfo, type EditorTree, type SchemaProperty } from "../api";
import { useAudioDevices, useDisplays, useObsInputs, useObsScenes, useObsSources, useRunningApps } from "./choices";
import { useObsInfo } from "../ObsPanel";
import { isVisible, properties } from "./schema";
import { KeySelect, ShortcutField, type Shortcut } from "./ShortcutField";
import { StepsField, SubActionField, type StepValue } from "./StepsField";

type PathKind = "exe" | "file" | "folder" | "audio";
// Widget -> kind of Windows file dialog its Browse button opens.
const PICK_KINDS: Record<string, PathKind> = { exe: "exe", file: "file", folder: "folder", "audio-file": "audio" };
const PLACEHOLDERS: Record<string, string> = {
  exe: "C:\\Program Files\\App\\App.exe",
  app: "C:\\Program Files\\App\\App.exe",
  file: "C:\\Users\\You\\Documents\\Project.xlsx",
  folder: "C:\\Users\\You\\Downloads",
  url: "https://example.com",
  "audio-file": "C:\\Users\\You\\Music\\Airhorn.mp3",
};

export interface ActionFieldsProps {
  tree: EditorTree;
  action: ActionInfo;
  config: Record<string, unknown>;
  errors: Record<string, string>;
  onChange: (config: Record<string, unknown>) => void;
  /** A program was chosen with Browse… or from running apps (auto-fills name and icon). */
  onPathPicked?: (path: string) => void;
  idPrefix?: string;
  /** Nested inside a Multi Action / Toggle. */
  nested?: boolean;
}

export function ActionFields({ tree, action, config, errors, onChange, onPathPicked, idPrefix = "action", nested }: ActionFieldsProps) {
  const fields = properties(action.configSchema).filter(([, prop]) => isVisible(prop, config, action.configSchema));
  const required = new Set(action.configSchema.required ?? []);

  return (
    <>
      {action.category === "streaming" && <ObsNotice />}
      {action.trustedOnly && !nested && (
        <p className="notice notice--warn">
          Runs exactly what you write here, on this PC, each time the key is pressed. Devices can only press the key;
          they can't see or change it.
        </p>
      )}
      {fields.length === 0 && !nested && <p className="field__hint">This action has no settings.</p>}
      {fields.map(([key, prop]) => (
        <Field
          key={`${action.type}.${key}`}
          id={`${idPrefix}-${key}`}
          name={key}
          tree={tree}
          prop={prop}
          required={required.has(key)}
          value={config[key]}
          config={config}
          error={errors[key]}
          onChange={(value) => onChange({ ...config, [key]: value })}
          onPathPicked={onPathPicked}
        />
      ))}
    </>
  );
}

interface FieldProps {
  id: string;
  name: string;
  tree: EditorTree;
  prop: SchemaProperty;
  required: boolean;
  value: unknown;
  /** All settings of the action, for fields that depend on another (OBS source -> scene). */
  config: Record<string, unknown>;
  error?: string;
  onChange: (value: unknown) => void;
  onPathPicked?: (path: string) => void;
}

function Field(props: FieldProps) {
  const { id, prop, required, value, error, onChange, tree } = props;
  const label = prop.title ?? props.name;
  const widget = prop.widget;
  const describedBy = [error && `${id}-error`, prop.description && `${id}-hint`].filter(Boolean).join(" ") || undefined;

  if (prop.type === "boolean") {
    return (
      <div className="field">
        <label className="switch-row">
          <input type="checkbox" className="switch" checked={Boolean(value ?? prop.default)} onChange={(e) => onChange(e.target.checked)} />
          <span>{label}</span>
        </label>
        {prop.description && <p className="field__hint field__hint--tight">{prop.description}</p>}
      </div>
    );
  }

  let control: React.ReactNode;
  if (widget === "steps") {
    control = <StepsField id={id} tree={tree} value={(value as StepValue[]) ?? []} onChange={onChange} />;
  } else if (widget === "action") {
    control = <SubActionField id={id} tree={tree} value={value as StepValue | undefined} onChange={onChange} />;
  } else if (widget === "hotkey" || widget === "key-combo") {
    control = (
      <ShortcutField
        id={id}
        keys={tree.keys}
        value={value as Shortcut | undefined}
        onChange={onChange}
        mode={widget === "hotkey" ? "record" : "compose"}
        invalid={Boolean(error)}
      />
    );
  } else if (widget === "key") {
    control = <KeySelect id={id} keys={tree.keys} value={(value as string) ?? ""} onChange={onChange} invalid={Boolean(error)} />;
  } else if (prop.enum) {
    control = (
      <select id={id} className="input" value={String(value ?? prop.default ?? "")} onChange={(e) => onChange(e.target.value)} aria-describedby={describedBy}>
        {prop.enum.map((option) => (
          <option key={option} value={option}>
            {prop.labels?.[option] ?? option}
          </option>
        ))}
      </select>
    );
  } else if (prop.type === "integer" || prop.type === "number") {
    control = <NumberInput id={id} prop={prop} value={value} onChange={onChange} invalid={Boolean(error)} describedBy={describedBy} />;
  } else if (widget === "audio-output" || widget === "audio-input") {
    control = <AudioDeviceSelect id={id} flow={widget === "audio-output" ? "output" : "input"} required={required} emptyLabel={prop.emptyLabel} value={(value as string) ?? ""} onChange={onChange} />;
  } else if (widget === "display") {
    control = <DisplaySelect id={id} value={(value as string) ?? ""} onChange={onChange} />;
  } else if (widget === "page" || widget === "profile") {
    control = <TreeSelect id={id} tree={tree} kind={widget} value={(value as string) ?? ""} onChange={onChange} invalid={Boolean(error)} />;
  } else if (widget === "obs-scene") {
    control = <ObsSceneSelect id={id} required={required} value={(value as string) ?? ""} onChange={onChange} invalid={Boolean(error)} />;
  } else if (widget === "obs-audio-input") {
    control = <ObsListSelect id={id} hook={() => useObsInputs("audio")} placeholder="Choose an audio source" value={(value as string) ?? ""} onChange={onChange} invalid={Boolean(error)} />;
  } else if (widget === "obs-source") {
    const sceneField = (prop as SchemaProperty & { sceneField?: string }).sceneField ?? "scene";
    const kind = (prop as SchemaProperty & { sourceKind?: string }).sourceKind ?? "all";
    const scene = String(props.config[sceneField] ?? "");
    control = (
      <ObsListSelect
        key={`${scene}:${kind}`}
        id={id}
        hook={() => useObsSources(scene, kind)}
        placeholder={kind === "video" ? "Choose a camera source" : "Choose a source"}
        value={(value as string) ?? ""}
        onChange={onChange}
        invalid={Boolean(error)}
      />
    );
  } else if (widget === "app") {
    control = <AppInput {...props} describedBy={describedBy} />;
  } else if (widget === "multiline" || widget === "code") {
    control = (
      <textarea
        id={id}
        className={widget === "code" ? "input textarea textarea--code" : "input textarea"}
        rows={widget === "code" ? 6 : 3}
        spellCheck={widget !== "code"}
        value={typeof value === "string" ? value : ""}
        maxLength={prop.maxLength}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
      />
    );
  } else {
    control = <TextInput {...props} describedBy={describedBy} />;
  }

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
        {!required && prop.default === undefined && <span className="field__optional"> (optional)</span>}
      </label>
      {control}
      {prop.description && widget !== "steps" && (
        <p id={`${id}-hint`} className="field__hint">
          {prop.description}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function NumberInput({ id, prop, value, onChange, invalid, describedBy }: { id: string; prop: SchemaProperty; value: unknown; onChange: (v: unknown) => void; invalid: boolean; describedBy?: string }) {
  const shown = value ?? prop.default ?? "";
  return (
    <div className="number-input">
      <input
        id={id}
        className="input"
        type="number"
        inputMode={prop.type === "integer" ? "numeric" : "decimal"}
        min={prop.minimum}
        max={prop.maximum}
        step={prop.type === "integer" ? 1 : "any"}
        value={String(shown)}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(raw === "" ? undefined : prop.type === "integer" ? Math.trunc(Number(raw)) : Number(raw));
        }}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
      />
      {prop.unit && <span className="number-input__unit">{prop.unit}</span>}
    </div>
  );
}

function TextInput({ id, prop, value, error, onChange, onPathPicked, describedBy }: FieldProps & { describedBy?: string }) {
  const [browsing, setBrowsing] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const widget = prop.widget ?? "text";
  const pickKind = PICK_KINDS[widget];
  const isPath = pickKind !== undefined;

  async function browse() {
    setBrowsing(true);
    setBrowseError(null);
    try {
      const { path } = await api.pick(pickKind);
      if (path) {
        onChange(path);
        if (widget === "exe") onPathPicked?.(path);
      }
    } catch (e) {
      setBrowseError(e instanceof ApiError ? e.message : "Couldn't open the file dialog.");
    } finally {
      setBrowsing(false);
    }
  }

  return (
    <>
      <div className={isPath ? "input-group" : undefined}>
        <input
          id={id}
          className="input"
          type={widget === "url" ? "url" : "text"}
          inputMode={widget === "url" ? "url" : undefined}
          spellCheck={false}
          autoComplete="off"
          value={typeof value === "string" ? value : ""}
          maxLength={prop.maxLength}
          placeholder={PLACEHOLDERS[widget]}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
        />
        {isPath && (
          <button type="button" className="btn" disabled={browsing} onClick={browse}>
            {browsing ? "Waiting…" : "Browse…"}
          </button>
        )}
      </div>
      {browsing && <p className="field__hint">Choose in the Windows dialog. It may open behind this window.</p>}
      {browseError && <p className="field__error">{browseError}</p>}
    </>
  );
}

/** A program: pick from apps with an open window, or browse for the .exe. */
function AppInput(props: FieldProps & { describedBy?: string }) {
  const { id, value, onChange, onPathPicked } = props;
  const { data: apps, error, refresh } = useRunningApps();
  return (
    <>
      <div className="input-group">
        <select
          className="input"
          aria-label="Running apps"
          value=""
          onChange={(e) => {
            if (!e.target.value) return;
            onChange(e.target.value);
            onPathPicked?.(e.target.value);
          }}
        >
          <option value="">{apps ? (apps.length ? "Choose a running app…" : "No apps with open windows") : "Loading running apps…"}</option>
          {apps?.map((app) => (
            <option key={app.path} value={app.path}>
              {app.name}
            </option>
          ))}
        </select>
        <button type="button" className="btn" onClick={refresh} title="Refresh the list of running apps">
          Refresh
        </button>
      </div>
      {error && <p className="field__error">{error}</p>}
      <div className="field__stack">
        <TextInput {...props} id={id} prop={{ ...props.prop, widget: "exe" }} value={value} onChange={onChange} />
      </div>
    </>
  );
}

function AudioDeviceSelect({ id, flow, required, emptyLabel, value, onChange }: { id: string; flow: "output" | "input"; required: boolean; emptyLabel?: string; value: string; onChange: (v: string) => void }) {
  const { data, error, refresh } = useAudioDevices(flow);
  const missing = value && data && !data.some((d) => d.id === value);
  return (
    <>
      <div className="input-group">
        <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
          {required ? (
            <option value="" disabled>
              Choose a device
            </option>
          ) : (
            <option value="">{emptyLabel ?? (flow === "output" ? "Default output (follows Windows)" : "Default microphone (follows Windows)")}</option>
          )}
          {data?.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
              {d.isDefault ? " (current default)" : ""}
            </option>
          ))}
          {missing && <option value={value}>Device not connected</option>}
        </select>
        <button type="button" className="btn" onClick={refresh}>
          Refresh
        </button>
      </div>
      {error && <p className="field__error">{error}</p>}
    </>
  );
}

function DisplaySelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const { data, error } = useDisplays();
  return (
    <>
      <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Primary display</option>
        {data?.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
            {d.primary ? " (primary)" : ""}
          </option>
        ))}
      </select>
      {error && <p className="field__error">{error}</p>}
    </>
  );
}

function TreeSelect({ id, tree, kind, value, onChange, invalid }: { id: string; tree: EditorTree; kind: "page" | "profile"; value: string; onChange: (v: string) => void; invalid: boolean }) {
  const profiles = [...tree.profiles].sort((a, b) => a.sortOrder - b.sortOrder);
  return (
    <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={invalid || undefined}>
      <option value="" disabled>
        {kind === "page" ? "Choose a page" : "Choose a profile"}
      </option>
      {kind === "profile"
        ? profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))
        : profiles.map((p) => (
            <optgroup key={p.id} label={p.name}>
              {tree.pages
                .filter((pg) => pg.profileId === p.id)
                .sort((a, b) => a.sortOrder - b.sortOrder)
                .map((pg) => (
                  <option key={pg.id} value={pg.id}>
                    {pg.name}
                  </option>
                ))}
            </optgroup>
          ))}
    </select>
  );
}

function ObsNotice() {
  const info = useObsInfo(3000);
  if (!info || info.status === "connected") return null;
  return (
    <p className="notice notice--warn">
      {info.status === "disabled"
        ? "OBS isn't connected yet. Set it up under Integrations in the sidebar. You can still save this key."
        : `OBS: ${info.message}`}
    </p>
  );
}

function ObsSceneSelect({ id, required, value, onChange, invalid }: { id: string; required: boolean; value: string; onChange: (v: string) => void; invalid: boolean }) {
  return (
    <ObsListSelect
      id={id}
      hook={useObsScenes}
      placeholder={required ? "Choose a scene" : "Current scene (whatever is live)"}
      emptyAllowed={!required}
      value={value}
      onChange={onChange}
      invalid={invalid}
    />
  );
}

/** A list read from OBS; keeps a typed value usable while OBS is offline. */
function ObsListSelect({
  id,
  hook,
  placeholder,
  emptyAllowed,
  value,
  onChange,
  invalid,
}: {
  id: string;
  hook: () => { data: string[] | null; error: string | null; refresh: () => void };
  placeholder: string;
  emptyAllowed?: boolean;
  value: string;
  onChange: (v: string) => void;
  invalid: boolean;
}) {
  const { data, error, refresh } = hook();
  if (error && !data) {
    // OBS offline: allow typing the exact name so keys can be prepared in advance.
    return (
      <>
        <div className="input-group">
          <input id={id} className="input" value={value} placeholder="Type the exact name used in OBS" onChange={(e) => onChange(e.target.value)} aria-invalid={invalid || undefined} />
          <button type="button" className="btn" onClick={refresh}>
            Refresh
          </button>
        </div>
        <p className="field__hint">{error}</p>
      </>
    );
  }
  const missing = value && data && !data.includes(value);
  return (
    <div className="input-group">
      <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={invalid || undefined}>
        <option value="" disabled={!emptyAllowed}>
          {data ? placeholder : "Loading from OBS…"}
        </option>
        {data?.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
        {missing && <option value={value}>{value} (not in OBS)</option>}
      </select>
      <button type="button" className="btn" onClick={refresh}>
        Refresh
      </button>
    </div>
  );
}
