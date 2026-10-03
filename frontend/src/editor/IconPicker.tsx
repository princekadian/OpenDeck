import { useRef, useState } from "react";
import { BUILTIN_ICONS, BuiltinIcon } from "../icons/BuiltinIcon";
import { KeyIcon } from "../icons/KeyIcon";
import { api, ApiError } from "./api";
import { ACCEPTED_ICON_TYPES, IconImageError, toIconPng } from "./iconImage";

interface Props {
  value: string | null;
  /** The action's default icon, shown when no icon is chosen. */
  fallback: string | null;
  /** Icon extracted from the chosen application, offered as a one-click option. */
  appIconRef: string | null;
  onChange: (iconRef: string | null) => void;
  /** Caption when no icon is chosen. */
  defaultCaption?: string;
}

export function IconPicker({ value, fallback, appIconRef, onChange, defaultCaption = "Default for this action" }: Props) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const png = await toIconPng(file);
      const { iconRef } = await api.uploadIcon(png);
      onChange(iconRef);
      setOpen(false);
    } catch (e) {
      setError(e instanceof IconImageError || e instanceof ApiError ? e.message : "Couldn't use that image.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="icon-picker">
      <div className="icon-picker__row">
        <span className="icon-picker__current" aria-hidden="true">
          <KeyIcon iconRef={value} fallback={fallback} className="icon-picker__current-icon" />
        </span>
        <span className="icon-picker__caption">{value ? describe(value, appIconRef) : defaultCaption}</span>
        <button type="button" className="btn btn-sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Done" : "Change"}
        </button>
      </div>

      {open && (
        <div className="icon-picker__panel">
          <div className="icon-picker__sources">
            {appIconRef && (
              <button type="button" className="btn btn-sm" onClick={() => onChange(appIconRef)}>
                Use application icon
              </button>
            )}
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => fileInput.current?.click()}>
              {busy ? "Uploading…" : "Upload image…"}
            </button>
            {value && (
              <button type="button" className="btn btn-sm btn-quiet" onClick={() => onChange(null)}>
                Use default
              </button>
            )}
            <input
              ref={fileInput}
              type="file"
              hidden
              accept={[".png", ".jpg", ".jpeg", ".svg", ...ACCEPTED_ICON_TYPES].join(",")}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void upload(file);
              }}
            />
          </div>
          {error && (
            <p className="field__error" role="alert">
              {error}
            </p>
          )}
          <div className="icon-grid" role="listbox" aria-label="Built-in icons">
            {BUILTIN_ICONS.map(({ name, label }) => {
              const ref = `builtin:${name}`;
              return (
                <button
                  key={name}
                  type="button"
                  role="option"
                  aria-selected={value === ref}
                  className="icon-grid__item"
                  title={label}
                  aria-label={label}
                  onClick={() => onChange(ref)}
                >
                  <BuiltinIcon name={name} />
                </button>
              );
            })}
          </div>
          <p className="field__hint">PNG, JPG or SVG. Images are resized to 256 × 256 px.</p>
        </div>
      )}
    </div>
  );
}

function describe(value: string, appIconRef: string | null): string {
  if (value === appIconRef) return "Application icon";
  if (value.startsWith("asset:")) return "Custom image";
  return BUILTIN_ICONS.find((i) => `builtin:${i.name}` === value)?.label ?? "Built-in icon";
}
