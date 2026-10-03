import { useEffect, useState } from "react";
import { bridge, desktopApi, DesktopApiError, type AppSettings, type HostState, type SettingsView as SettingsData } from "./api";
import { Facts } from "./parts";

interface Props {
  host: HostState | null;
  notify: (text: string, error?: boolean) => void;
}

const REPO_DOCS = "docs/NETWORKING.md";

/** Only settings the app really supports. Changes apply when saved. */
export function SettingsView({ host, notify }: Props) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [paths, setPaths] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    desktopApi.settings().then((d) => {
      setData(d);
      setDraft(d.settings);
    }, () => notify("Couldn't load settings.", true));
    desktopApi.diagnostics().then(setPaths, () => undefined);
  }, [notify]);

  if (!data || !draft) return <div className="view" aria-busy="true" />;
  const dirty = JSON.stringify(draft) !== JSON.stringify(data.settings);
  const set = (patch: Partial<AppSettings>) => setDraft({ ...draft, ...patch });

  async function save() {
    if (!draft) return;
    setSaving(true);
    setErrors({});
    try {
      const next = await desktopApi.saveSettings(draft);
      setData(next);
      setDraft(next.settings);
      notify("Settings saved");
    } catch (e) {
      if (e instanceof DesktopApiError) {
        setErrors(e.fields);
        notify(e.message, true);
      } else notify("Couldn't save settings.", true);
    } finally {
      setSaving(false);
    }
  }

  const useful = data.interfaces.filter((i) => i.useful);
  const other = data.interfaces.filter((i) => !i.useful);

  return (
    <div className="view settings">
      <header className="view__head">
        <h1 className="view__title">Settings</h1>
      </header>

      <form
        className="settings__form"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <section className="settings__section" aria-labelledby="s-general">
          <h2 id="s-general" className="settings__title">General</h2>
          <Toggle
            label="Start OpenDeck with Windows"
            hint={data.startWithWindowsAvailable ? "Starts in the notification area when you sign in." : "Available in the installed app."}
            checked={draft.startWithWindows}
            disabled={!data.startWithWindowsAvailable}
            onChange={(v) => set({ startWithWindows: v })}
          />
          <Toggle
            label="Keep running in the notification area when the window is closed"
            hint="The server keeps running for your devices. Use Exit in the tray menu to quit."
            checked={draft.minimizeToTray}
            onChange={(v) => set({ minimizeToTray: v })}
          />
        </section>

        <section className="settings__section" aria-labelledby="s-server">
          <h2 id="s-server" className="settings__title">Server</h2>
          <div className="field">
            <label className="field__label" htmlFor="set-host">
              Accept connections from
            </label>
            <select id="set-host" className="input" value={draft.serverHost} onChange={(e) => set({ serverHost: e.target.value as AppSettings["serverHost"] })}>
              <option value="0.0.0.0">Devices on your local network (needed for phones and tablets)</option>
              <option value="127.0.0.1">This PC only</option>
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="set-port">
              Port
            </label>
            <input
              id="set-port"
              className="input input-narrow"
              type="number"
              min={1024}
              max={65535}
              value={draft.serverPort}
              disabled={data.portFromEnvironment}
              aria-invalid={errors.serverPort ? true : undefined}
              onChange={(e) => set({ serverPort: Number(e.target.value) })}
            />
            {errors.serverPort && <p className="field__error">{errors.serverPort}</p>}
            <p className="field__hint">
              {data.portFromEnvironment
                ? "Set by the OPENDECK_PORT environment variable."
                : "1024–65535. If the server is running it restarts on the new port, and devices need the new address."}
            </p>
          </div>
          <Toggle
            label="Start the server when OpenDeck starts"
            checked={draft.autoStartServer}
            onChange={(v) => set({ autoStartServer: v })}
          />
        </section>

        <section className="settings__section" aria-labelledby="s-remote">
          <h2 id="s-remote" className="settings__title">Remote control</h2>
          <div className="field">
            <label className="field__label" htmlFor="set-iface">
              Address shown to devices
            </label>
            <select
              id="set-iface"
              className="input"
              value={draft.preferredAddress ?? ""}
              onChange={(e) => set({ preferredAddress: e.target.value || null })}
            >
              <option value="">Automatic ({useful[0] ? `${useful[0].address} · ${useful[0].name}` : "none found"})</option>
              {useful.map((i) => (
                <option key={i.address} value={i.address}>
                  {i.address} · {i.name}
                </option>
              ))}
              {other.length > 0 && (
                <optgroup label="Virtual adapters (usually not reachable from phones)">
                  {other.map((i) => (
                    <option key={i.address} value={i.address}>
                      {i.address} · {i.name}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            <p className="field__hint">Pair, rename and remove devices in Devices.</p>
          </div>
        </section>

        <section className="settings__section" aria-labelledby="s-logging">
          <h2 id="s-logging" className="settings__title">Logging</h2>
          <div className="field">
            <label className="field__label" htmlFor="set-level">
              Detail
            </label>
            <select id="set-level" className="input input-narrow" value={draft.logLevel} onChange={(e) => set({ logLevel: e.target.value as AppSettings["logLevel"] })}>
              <option value="INFO">Normal</option>
              <option value="DEBUG">Detailed (for troubleshooting)</option>
              <option value="WARNING">Warnings and errors only</option>
              <option value="ERROR">Errors only</option>
            </select>
            <p className="field__hint">Log files rotate at 2 MB; the 5 most recent are kept.</p>
          </div>
          <button type="button" className="btn" onClick={() => desktopApi.open("logs")}>
            Open logs folder
          </button>
        </section>

        <section className="settings__section" aria-labelledby="s-data">
          <h2 id="s-data" className="settings__title">Data</h2>
          {paths && (
            <Facts
              items={[
                ["Data folder", String(paths.dataDirectory ?? "")],
                ["Database", String(paths.databasePath ?? "")],
                ["Backups", String(paths.backupDirectory ?? "")],
              ]}
            />
          )}
          <div className="settings__row">
            <button type="button" className="btn" onClick={() => desktopApi.open("data")}>
              Open data folder
            </button>
            <button
              type="button"
              className="btn"
              onClick={async () => {
                try {
                  await desktopApi.backup();
                  notify("Backup saved in the backups folder");
                } catch {
                  notify("Backup failed. See Logs.", true);
                }
              }}
            >
              Back up now
            </button>
            <button type="button" className="btn" onClick={() => desktopApi.open("backups")}>
              Open backups folder
            </button>
          </div>
          <p className="field__hint">Updating or reinstalling OpenDeck never changes this folder. Uninstalling asks before removing it.</p>
        </section>

        <section className="settings__section" aria-labelledby="s-help">
          <h2 id="s-help" className="settings__title">Help: a device can't connect</h2>
          <ol className="settings__help">
            <li>Phone and PC must be on the same Wi-Fi (not a guest network).</li>
            <li>In Windows Settings › Network &amp; internet, set this Wi-Fi to <strong>Private</strong>.</li>
            <li>The installer allows OpenDeck through Windows Firewall on private networks. If you ran it from source, run <code>scripts\allow-firewall.ps1</code> as administrator.</li>
            <li>Check that the server is running and open the address shown on the Dashboard.</li>
          </ol>
          <p className="field__hint">More in {REPO_DOCS} in the project repository.</p>
        </section>

        <section className="settings__section" aria-labelledby="s-about">
          <h2 id="s-about" className="settings__title">About</h2>
          <Facts
            items={[
              ["Version", `OpenDeck v${host?.version ?? String(paths?.version ?? "")}`],
              ["License", "MIT — free and open source"],
              ["Runs", "Entirely on this PC and your local network. No account or cloud service."],
            ]}
          />
          {bridge() && (
            <button type="button" className="btn btn-quiet-danger" onClick={() => bridge()?.host_command("exit")}>
              Exit OpenDeck
            </button>
          )}
        </section>

        <div className="settings__bar" data-visible={dirty || undefined}>
          <span>You have unsaved changes.</span>
          <button type="button" className="btn" onClick={() => setDraft(data.settings)} disabled={saving}>
            Discard
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving || !dirty}>
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Toggle({ label, hint, checked, disabled, onChange }: { label: string; hint?: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="toggle-row" data-disabled={disabled || undefined}>
      <input type="checkbox" className="switch" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-row__text">
        <span>{label}</span>
        {hint && <span className="field__hint">{hint}</span>}
      </span>
    </label>
  );
}
