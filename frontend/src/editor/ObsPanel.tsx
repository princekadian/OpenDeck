// Integrations: OBS Studio connection settings and live status.

import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type ObsInfo } from "./api";
import { clearChoiceCache } from "./actionForm/choices";

const STATUS: Record<ObsInfo["status"], { tone?: string; label: string }> = {
  connected: { tone: "online", label: "Connected" },
  connecting: { tone: "busy", label: "Connecting" },
  unreachable: { tone: "error", label: "Not reachable" },
  auth_failed: { tone: "error", label: "Wrong password" },
  disabled: { label: "Off" },
};

export function useObsInfo(pollMs = 2000): ObsInfo | null {
  const [info, setInfo] = useState<ObsInfo | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.obs().then((i) => alive && setInfo(i)).catch(() => undefined);
    void load();
    const timer = setInterval(() => document.visibilityState === "visible" && void load(), pollMs);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [pollMs]);
  return info;
}

export function ObsPanel() {
  const info = useObsInfo();
  const [form, setForm] = useState<{ enabled: boolean; host: string; port: string; password: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (info && !form) {
      setForm({ enabled: info.settings.enabled, host: info.settings.host, port: String(info.settings.port), password: "" });
    }
  }, [info, form]);

  async function save(e?: FormEvent, enabled = form?.enabled) {
    e?.preventDefault();
    if (!form) return;
    setSaving(true);
    setError(null);
    try {
      await api.saveObs({
        enabled: Boolean(enabled),
        host: form.host.trim() || "127.0.0.1",
        port: Number(form.port) || 4455,
        // Empty field keeps the saved password; the password is never shown again.
        password: form.password ? form.password : null,
      });
      clearChoiceCache();
      setForm({ ...form, enabled: Boolean(enabled), password: "" });
    } catch (err) {
      setError(err instanceof ApiError ? (Object.values(err.fields)[0] ?? err.message) : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  const status = info ? STATUS[info.status] : null;
  return (
    <section className="integration" aria-labelledby="obs-title">
      <header className="integration__head">
        <div>
          <h1 id="obs-title" className="canvas__title">
            OBS Studio
          </h1>
          <p className="canvas__crumb">Control streaming, recording, scenes and sources. Keys show what OBS is doing.</p>
        </div>
        {status && (
          <span className="status-pill" role="status">
            <span className="led" data-tone={status.tone} aria-hidden="true" />
            {status.label}
          </span>
        )}
      </header>

      {info && <p className="integration__message">{info.message}</p>}

      {form && (
        <form className="integration__form" onSubmit={save} noValidate>
          <label className="switch-row">
            <input
              type="checkbox"
              className="switch"
              checked={form.enabled}
              onChange={(e) => {
                setForm({ ...form, enabled: e.target.checked });
                void save(undefined, e.target.checked);
              }}
            />
            <span>Connect to OBS</span>
          </label>
          <div className="field-row">
            <div className="field" style={{ flex: "1 1 220px" }}>
              <label className="field__label" htmlFor="obs-host">
                Address
              </label>
              <input id="obs-host" className="input" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} spellCheck={false} />
            </div>
            <div className="field" style={{ flex: "0 1 120px" }}>
              <label className="field__label" htmlFor="obs-port">
                Port
              </label>
              <input id="obs-port" className="input" inputMode="numeric" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value.replace(/\D/g, "") })} />
            </div>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="obs-password">
              Server password
            </label>
            <input
              id="obs-password"
              className="input"
              type="password"
              autoComplete="off"
              value={form.password}
              placeholder={info?.settings.hasPassword ? "Saved. Type to replace it" : "From OBS: Show Connect Info"}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
            <p className="field__hint">Stored encrypted for your Windows account. It is never sent to devices.</p>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save and connect"}
          </button>
        </form>
      )}

      <section className="integration__help" aria-labelledby="obs-help">
        <h2 id="obs-help">Set up OBS (once)</h2>
        <ol>
          <li>In OBS, open Tools, then WebSocket Server Settings.</li>
          <li>Turn on Enable WebSocket server. Keep the port 4455.</li>
          <li>Select Show Connect Info and copy the server password into the field above.</li>
          <li>OBS can run on this PC (address 127.0.0.1) or on another PC on your network.</li>
        </ol>
      </section>
    </section>
  );
}
