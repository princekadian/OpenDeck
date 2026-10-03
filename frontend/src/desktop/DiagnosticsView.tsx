import { useEffect, useState } from "react";
import { bridge, desktopApi, type HostState, type SystemInfo } from "./api";
import { formatBytes, formatDuration } from "./hooks";
import { Facts, Panel } from "./parts";

const LABELS: Array<[string, string]> = [
  ["application", "Application"],
  ["protocolVersion", "Protocol version"],
  ["windows", "Windows"],
  ["python", "Python"],
  ["packaged", "Installed build"],
  ["enginePid", "Engine process"],
  ["engineUptimeSeconds", "Engine uptime"],
  ["serverState", "Server state"],
  ["serverError", "Server error"],
  ["host", "Host"],
  ["port", "Port"],
  ["lanAddresses", "LAN addresses"],
  ["remoteUrls", "Remote URLs"],
  ["connectedDevices", "Connected devices"],
  ["pairedDevices", "Paired devices"],
  ["databaseOk", "Database OK"],
  ["schemaVersion", "Database schema"],
  ["databasePath", "Database"],
  ["dataDirectory", "Data folder"],
  ["logDirectory", "Log folder"],
  ["backupDirectory", "Backup folder"],
  ["obs", "OBS"],
];

/** Everything a bug report needs, copyable in one click. */
export function DiagnosticsView({ host, system, notify }: { host: HostState | null; system: SystemInfo | null; notify: (text: string, error?: boolean) => void }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const load = () => desktopApi.diagnostics().then(setData, () => notify("Couldn't read diagnostics.", true));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const show = (key: string, value: unknown): string => {
    if (key === "engineUptimeSeconds") return formatDuration(value as number);
    if (Array.isArray(value)) return value.join(", ") || "—";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    return value == null || value === "" ? "—" : String(value);
  };
  const rows: Array<[string, string]> = data ? LABELS.filter(([k]) => k in data).map(([k, label]) => [label, show(k, data[k])]) : [];
  if (host) rows.push(["Desktop process", String(host.hostPid)], ["Window process", String(host.uiPid ?? "—")]);
  if (system) {
    for (const [name, p] of Object.entries(system.processes)) {
      if (p) rows.push([`RAM · ${name}`, `${formatBytes(p.workingSet)} (pid ${p.pid}, ${p.cpuSeconds} s CPU)`]);
    }
  }

  async function copy() {
    await navigator.clipboard.writeText(rows.map(([k, v]) => `${k}: ${v}`).join("\n"));
    notify("Diagnostics copied");
  }

  return (
    <div className="view">
      <header className="view__head">
        <h1 className="view__title">Diagnostics</h1>
        <div className="view__actions">
          <button type="button" className="btn" onClick={() => void load()}>
            Refresh
          </button>
          <button type="button" className="btn btn-primary" onClick={() => void copy()} disabled={!data}>
            Copy diagnostics
          </button>
        </div>
      </header>
      <Panel
        title="System report"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => desktopApi.open("logs")}>
              Open logs
            </button>
            <button type="button" className="btn btn-sm" onClick={() => desktopApi.open("data")}>
              Open data folder
            </button>
            <button
              type="button"
              className="btn btn-sm"
              onClick={async () => {
                await desktopApi.serverCommand("restart");
                notify("Server restarted");
                void load();
              }}
            >
              Restart server
            </button>
            {bridge() && (
              <button type="button" className="btn btn-sm" onClick={() => bridge()?.host_command("restart-engine")}>
                Restart engine
              </button>
            )}
          </>
        }
      >
        {data ? <Facts items={rows} /> : <p className="empty">Loading…</p>}
        <p className="field__hint">Paste this into a GitHub issue. It contains no pairing codes, tokens or passwords; folder paths include your Windows user name.</p>
      </Panel>
    </div>
  );
}
