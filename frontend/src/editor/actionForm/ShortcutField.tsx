// Keyboard shortcut settings, stored structurally: {"modifiers": ["CTRL","SHIFT"], "key": "S"}.

import { useState, type KeyboardEvent } from "react";
import type { KeyInfo } from "../api";

export interface Shortcut {
  modifiers: string[];
  key: string;
}

const MODIFIERS: Array<[string, string]> = [
  ["CTRL", "Ctrl"],
  ["ALT", "Alt"],
  ["SHIFT", "Shift"],
  ["WIN", "Win"],
];

// KeyboardEvent.code -> backend key name.
const CODE_NAMES: Record<string, string> = {
  Enter: "ENTER", NumpadEnter: "ENTER", Escape: "ESCAPE", Space: "SPACE", Tab: "TAB", Backspace: "BACKSPACE",
  Delete: "DELETE", Insert: "INSERT", Home: "HOME", End: "END", PageUp: "PAGE_UP", PageDown: "PAGE_DOWN",
  ArrowLeft: "LEFT", ArrowRight: "RIGHT", ArrowUp: "UP", ArrowDown: "DOWN", CapsLock: "CAPS_LOCK",
  NumLock: "NUM_LOCK", ScrollLock: "SCROLL_LOCK", PrintScreen: "PRINT_SCREEN", Pause: "PAUSE",
  ContextMenu: "CONTEXT_MENU", Semicolon: "SEMICOLON", Equal: "EQUALS", Comma: "COMMA", Minus: "MINUS",
  Period: "PERIOD", Slash: "SLASH", Backquote: "BACKQUOTE", BracketLeft: "BRACKET_LEFT", Backslash: "BACKSLASH",
  BracketRight: "BRACKET_RIGHT", Quote: "QUOTE", NumpadMultiply: "NUMPAD_MULTIPLY", NumpadAdd: "NUMPAD_ADD",
  NumpadSubtract: "NUMPAD_SUBTRACT", NumpadDecimal: "NUMPAD_DECIMAL", NumpadDivide: "NUMPAD_DIVIDE",
  MediaPlayPause: "MEDIA_PLAY_PAUSE", MediaTrackNext: "MEDIA_NEXT", MediaTrackPrevious: "MEDIA_PREVIOUS",
  MediaStop: "MEDIA_STOP", AudioVolumeUp: "VOLUME_UP", AudioVolumeDown: "VOLUME_DOWN", AudioVolumeMute: "VOLUME_MUTE",
};

export function keyNameFromCode(code: string): string | null {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit\d$/.test(code)) return code.slice(5);
  if (/^F\d{1,2}$/.test(code)) return code;
  if (/^Numpad\d$/.test(code)) return `NUMPAD_${code.slice(6)}`;
  return CODE_NAMES[code] ?? null;
}

const MODIFIER_CODES = new Set(["ControlLeft", "ControlRight", "AltLeft", "AltRight", "ShiftLeft", "ShiftRight", "MetaLeft", "MetaRight"]);

export function formatShortcut(value: Shortcut | undefined, keys: KeyInfo[]): string {
  if (!value?.key) return "";
  const label = keys.find((k) => k.name === value.key)?.label ?? value.key;
  return [...MODIFIERS.filter(([m]) => value.modifiers?.includes(m)).map(([, l]) => l), label].join(" + ");
}

interface Props {
  id: string;
  value: Shortcut | undefined;
  keys: KeyInfo[];
  onChange: (value: Shortcut) => void;
  /** Start with the recorder (Hotkey) or with the lists (Key combination). */
  mode: "record" | "compose";
  invalid?: boolean;
}

export function ShortcutField({ id, value, keys, onChange, mode, invalid }: Props) {
  const [recording, setRecording] = useState(false);
  const [compose, setCompose] = useState(mode === "compose");
  const [hint, setHint] = useState<string | null>(null);

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    if (!recording) return;
    e.preventDefault();
    e.stopPropagation();
    if (MODIFIER_CODES.has(e.code)) return; // wait for the main key
    const key = keyNameFromCode(e.code);
    if (!key) {
      setHint("That key can't be used. Choose it from the lists instead.");
      return;
    }
    const modifiers = [e.ctrlKey && "CTRL", e.altKey && "ALT", e.shiftKey && "SHIFT", e.metaKey && "WIN"].filter(Boolean) as string[];
    onChange({ modifiers, key });
    setRecording(false);
    setHint(null);
  }

  const groups = [...new Set(keys.map((k) => k.group))];
  const current = formatShortcut(value, keys);

  return (
    <div className="shortcut" data-invalid={invalid || undefined}>
      {!compose ? (
        <>
          <button
            id={id}
            type="button"
            className="shortcut__recorder"
            data-recording={recording || undefined}
            aria-pressed={recording}
            aria-label={recording ? "Recording: press the shortcut now" : current ? `Shortcut ${current}. Record again` : "Record shortcut"}
            onClick={() => {
              setRecording((r) => !r);
              setHint(null);
            }}
            onKeyDown={onKeyDown}
            onBlur={() => setRecording(false)}
          >
            {recording ? "Press the shortcut now…" : current ? <kbd>{current}</kbd> : "Record shortcut"}
          </button>
          <p className="field__hint">
            {hint ??
              (recording
                ? "Some shortcuts (like Ctrl + W or the Windows key) are taken by the browser or Windows. Use the lists for those."
                : current
                  ? "Click to record a different shortcut."
                  : "Click, then press the keys together.")}
          </p>
        </>
      ) : (
        <div className="shortcut__compose">
          <div className="shortcut__mods" role="group" aria-label="Modifier keys">
            {MODIFIERS.map(([name, label]) => {
              const on = value?.modifiers?.includes(name) ?? false;
              return (
                <label key={name} className="chip-toggle">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => {
                      const mods = on ? (value?.modifiers ?? []).filter((m) => m !== name) : [...(value?.modifiers ?? []), name];
                      onChange({ modifiers: mods, key: value?.key ?? "" });
                    }}
                  />
                  <span>{label}</span>
                </label>
              );
            })}
          </div>
          <span className="shortcut__plus" aria-hidden="true">
            +
          </span>
          <KeySelect id={id} keys={keys} groups={groups} value={value?.key ?? ""} onChange={(key) => onChange({ modifiers: value?.modifiers ?? [], key })} />
        </div>
      )}
      <button type="button" className="btn btn-sm btn-quiet shortcut__switch" onClick={() => setCompose((c) => !c)}>
        {compose ? "Record with the keyboard instead" : "Choose keys from lists instead"}
      </button>
    </div>
  );
}

export function KeySelect({
  id,
  keys,
  groups,
  value,
  onChange,
  invalid,
}: {
  id: string;
  keys: KeyInfo[];
  groups?: string[];
  value: string;
  onChange: (key: string) => void;
  invalid?: boolean;
}) {
  const list = groups ?? [...new Set(keys.map((k) => k.group))];
  return (
    <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={invalid || undefined}>
      <option value="" disabled>
        Choose a key
      </option>
      {list.map((group) => (
        <optgroup key={group} label={group}>
          {keys
            .filter((k) => k.group === group)
            .map((k) => (
              <option key={k.name} value={k.name}>
                {k.label}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}
