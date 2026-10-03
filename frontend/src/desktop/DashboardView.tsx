import { useEffect, useState } from "react";
import { desktopApi, DesktopApiError, type Health, type HostStatus, type ServerInfo, type SystemInfo } from "./api";
import { deviceType, formatBytes, formatDuration } from "./hooks";
import { CopyButton, Facts, Panel, QrCode, StateChip } from "./parts";

interface Props {
  info: ServerInfo | null;
  engineDown: boolean;
  onInfo: (info: ServerInfo) => void;
  system: SystemInfo | null;
  go: (view: string) => void;
  notify: (text: string, error?: boolean) => void;
}

/** At a glance: is the server up, how phones connect, who is connected. */
export function DashboardView({ info, engineDown, onInfo, system, go, notify }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [status, setStatus] = useState<HostStatus | null>(null);

  // Device list and pairing code: refreshed when the server state changes, plus every 10 s
  // while the dashboard is on screen (devices connect without changing server state).
  useEffect(() => {
    let alive = true;
    const load = () => {
      desktopApi.status().then((s) => alive && setStatus(s), () => undefined);
      desktopApi.health().then((h) => alive && setHealth(h), () => undefined);
    };
    load();
    const timer = setInterval(() => document.visibilityState === "visible" && load(), 10_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [info?.version, info?.devices]);

  async function command(name: "start" | "stop" | "restart") {
    setBusy(name);
    try {
      const next = await desktopApi.serverCommand(name);
      onInfo(next);
      if (next.state === "error") notify(next.error ?? "The server couldn't start.", true);
    } catch (e) {
      notify(e instanceof DesktopApiError ? e.message : "That didn't work.", true);
    } finally {
      setBusy(null);
    }
  }

  const state = engineDown ? "engine-down" : (info?.state ?? "stopped");
  const running = info?.state === "running";
  const url = running ? info.urls[0] : undefined;
  const connected = status?.connectedDevices ?? [];

  return (
    <div className="view dashboard">
      <header className="view__head">
        <h1 className="view__title">Dashboard</h1>
      </header>

      <div className="dashboard__grid">
        <Panel title="Remote control server" className="dashboard__server">
          <div className="server-card">
            <StateChip state={state} />
            {info?.state === "error" && info.error && (
              <p className="server-card__error" role="alert">
                {info.error}{" "}
                <button type="button" className="link" onClick={() => go("settings")}>
                  Open server settings
                </button>
              </p>
            )}
            <p className="server-card__meta">
              {running
                ? `Listening on port ${info.port} for ${info.lanOnly ? "devices on your network" : "this PC only"} · up ${formatDuration(info.uptimeSeconds)}`
                : info?.state === "stopped"
                  ? "Phones and tablets can't connect until you start the server. You can keep editing."
                  : " "}
            </p>
            <div className="server-card__actions">
              {running ? (
                <>
                  <button type="button" className="btn" disabled={!!busy} onClick={() => command("stop")}>
                    {busy === "stop" ? "Stopping…" : "Stop server"}
                  </button>
                  <button type="button" className="btn" disabled={!!busy} onClick={() => command("restart")}>
                    {busy === "restart" ? "Restarting…" : "Restart"}
                  </button>
                </>
              ) : (
                <button type="button" className="btn btn-primary" disabled={!!busy || engineDown || info?.state === "starting"} onClick={() => command("start")}>
                  {busy === "start" ? "Starting…" : "Start server"}
                </button>
              )}
            </div>
          </div>
        </Panel>

        <Panel title="Connect a phone or tablet" className="dashboard__remote">
          {url ? (
            <div className="remote">
              <div className="remote__text">
                <p className="remote__lead">Open this address in Safari or Chrome on a device on the same Wi-Fi:</p>
                <output className="remote__url">{url}</output>
                <div className="remote__buttons">
                  <CopyButton text={url} label="Copy address" />
                  <button type="button" className="btn" onClick={() => desktopApi.open("remote")}>
                    Open
                  </button>
                </div>
                {status && (
                  <p className="remote__pair">
                    First time? Enter pairing code <strong className="remote__code">{status.pairing.code}</strong> on the device.
                  </p>
                )}
                {info && info.urls.length > 1 && <p className="field__hint">Other addresses: {info.urls.slice(1).join(", ")}</p>}
                <p className="field__hint">
                  Device can't connect? Allow OpenDeck in Windows Firewall and make sure your Wi-Fi is set to Private. See Help in Settings.
                </p>
              </div>
              <div className="remote__qr">
                <QrCode text={url} />
                <span className="field__hint">Scan with the camera</span>
              </div>
            </div>
          ) : info && !info.lanOnly ? (
            <p className="empty">The server only accepts this PC. Choose “Devices on your network” in Settings to connect phones.</p>
          ) : running ? (
            <p className="empty">No network connection found. Connect this PC to the same Wi-Fi as your device.</p>
          ) : (
            <p className="empty">Start the server to get the address for your phone or tablet.</p>
          )}
        </Panel>

        <Panel
          title="Devices"
          className="dashboard__devices"
          actions={
            <button type="button" className="btn btn-sm" onClick={() => go("devices")}>
              Manage
            </button>
          }
        >
          {connected.length === 0 ? (
            <p className="empty">No device connected right now.</p>
          ) : (
            <ul className="mini-list">
              {connected.map((d) => (
                <li key={d.sessionId}>
                  <span className="led" data-tone="online" aria-hidden="true" />
                  <span className="mini-list__name">{d.deviceName}</span>
                  <span className="mini-list__meta">
                    {deviceType(d.userAgent)} · {d.remote}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {status && (
            <p className="field__hint">
              {status.pairedDevices.filter((d) => !d.revoked).length} paired · {connected.length} connected
            </p>
          )}
        </Panel>

        <Panel title="Application" className="dashboard__app">
          <Facts
            items={[
              ["Version", health ? `OpenDeck ${health.version}` : "—"],
              ["Engine uptime", formatDuration(health?.uptimeSeconds)],
              ["Database", health ? (health.database.ok ? `OK · schema ${health.database.schemaVersion}` : "Problem — see Logs") : "—"],
              ["Device connections", running ? `${info.devices} open` : "Server stopped"],
            ]}
          />
        </Panel>

        <Panel title="This PC" className="dashboard__system">
          <Facts
            items={[
              ["CPU", system?.cpu != null ? `${Math.round(system.cpu)}%` : "—"],
              ["Memory", system ? `${Math.round(system.memory.usage)}% of ${formatBytes(system.memory.total)}` : "—"],
              [
                "OpenDeck uses",
                system
                  ? formatBytes(Object.values(system.processes).reduce((sum, p) => sum + (p?.workingSet ?? 0), 0)) + " RAM (excluding the window's browser engine)"
                  : "—",
              ],
            ]}
          />
          <button type="button" className="link" onClick={() => go("monitoring")}>
            Open System Monitoring
          </button>
        </Panel>
      </div>
    </div>
  );
}
