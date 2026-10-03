import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog, PromptDialog } from "../editor/Modal";
import { desktopApi, DesktopApiError, type HostStatus } from "./api";
import { deviceType } from "./hooks";
import { Panel } from "./parts";

/** Pairing and paired devices. Only paired devices can press buttons. */
export function DevicesView({ notify }: { notify: (text: string, error?: boolean) => void }) {
  const [status, setStatus] = useState<HostStatus | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [removing, setRemoving] = useState<{ id: string; name: string } | null>(null);

  const load = useCallback(() => desktopApi.status().then(setStatus, () => undefined), []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => document.visibilityState === "visible" && void load(), 5000);
    return () => clearInterval(timer);
  }, [load]);

  if (!status) return <div className="view" aria-busy="true" />;
  const sessions = new Map(status.connectedDevices.map((s) => [s.deviceId, s]));
  const paired = status.pairedDevices.filter((d) => !d.revoked);

  return (
    <div className="view devices">
      <header className="view__head">
        <h1 className="view__title">Devices</h1>
      </header>

      <Panel title="Pair a new device">
        <div className="pair">
          <p className="pair__code" aria-label={`Pairing code ${status.pairing.code.split("").join(" ")}`}>
            {status.pairing.code.slice(0, 3)}
            <span className="pair__gap" aria-hidden="true" />
            {status.pairing.code.slice(3)}
          </p>
          <div>
            <p>Open the remote address on the phone or tablet, then enter this code.</p>
            <p className="field__hint">
              Valid for {Math.max(1, Math.ceil(status.pairing.expiresIn / 60))} min · each code works once ·{" "}
              {status.urls[0] ? `address ${status.urls[0]}` : "start the server first"}
            </p>
          </div>
        </div>
      </Panel>

      <Panel title={`Paired devices (${paired.length})`}>
        {paired.length === 0 ? (
          <p className="empty">No devices paired yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th>IP address</th>
                <th>Last connected</th>
                <th>Paired</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {paired.map((d) => {
                const session = sessions.get(d.id);
                return (
                  <tr key={d.id}>
                    <td className="table__strong">{d.name}</td>
                    <td>{session ? deviceType(session.userAgent) : "—"}</td>
                    <td>
                      <span className="device-state" data-online={session ? "" : undefined}>
                        <span className="led" data-tone={session ? "online" : undefined} aria-hidden="true" />
                        {session ? "Connected" : "Not connected"}
                      </span>
                    </td>
                    <td>{session?.remote ?? "—"}</td>
                    <td>{session ? "Now" : formatWhen(d.lastSeenAt)}</td>
                    <td>{formatWhen(d.pairedAt)}</td>
                    <td className="table__actions">
                      <button type="button" className="btn btn-sm" onClick={() => setRenaming({ id: d.id, name: d.name })}>
                        Rename
                      </button>
                      <button type="button" className="btn btn-sm btn-quiet-danger" onClick={() => setRemoving({ id: d.id, name: d.name })}>
                        Remove
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="field__hint">A device you remove is disconnected at once and has to pair again. Devices reconnect by themselves after the server restarts.</p>
      </Panel>

      {renaming && (
        <PromptDialog
          title="Rename device"
          label="Name"
          initial={renaming.name}
          confirmLabel="Rename"
          onClose={() => setRenaming(null)}
          onSubmit={async (name) => {
            try {
              await desktopApi.renameDevice(renaming.id, name);
              await load();
            } catch (e) {
              return e instanceof DesktopApiError ? e.message : "Couldn't rename.";
            }
          }}
        />
      )}
      {removing && (
        <ConfirmDialog
          title="Remove device?"
          message={`${removing.name} will be disconnected and must pair again to use OpenDeck.`}
          confirmLabel="Remove device"
          danger
          onClose={() => setRemoving(null)}
          onConfirm={() => {
            void desktopApi.revokeDevice(removing.id).then(() => {
              notify(`${removing.name} removed`);
              void load();
            });
          }}
        />
      )}
    </div>
  );
}

function formatWhen(iso: string | null): string {
  if (!iso) return "Never";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
