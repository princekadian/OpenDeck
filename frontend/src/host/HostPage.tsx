// PC-side welcome/pairing page. Served to localhost only (admin API rejects LAN clients).

import { useCallback, useEffect, useState } from "react";
import { PRODUCT_NAME } from "../branding";
import "./host.css";

interface HostStatus {
  pcName: string;
  port: number;
  urls: string[];
  pairing: { code: string; expiresIn: number };
  connectedDevices: Array<{ sessionId: string; deviceId: string; deviceName: string; remote: string }>;
  pairedDevices: Array<{ id: string; name: string; pairedAt: string; lastSeenAt: string | null; revoked: boolean }>;
}

const POLL_MS = 2_000;

/** Address, pairing code and paired devices. Shown in the editor's Connect devices view. */
export function HostPage() {
  const [status, setStatus] = useState<HostStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/admin/status");
      if (response.status === 403) {
        setError("This page only works on the PC running " + PRODUCT_NAME + ".");
        return;
      }
      setStatus((await response.json()) as HostStatus);
      setError(null);
    } catch {
      setError(PRODUCT_NAME + " is not running.");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const primaryUrl = status?.urls[0];

  async function copyAddress() {
    if (!primaryUrl) return;
    await navigator.clipboard.writeText(primaryUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function revoke(deviceId: string, name: string) {
    if (!confirm(`Remove ${name}? It will need to pair again.`)) return;
    await fetch(`/api/admin/devices/${encodeURIComponent(deviceId)}/revoke`, { method: "POST" });
    void load();
  }

  if (error) {
    return (
      <section className="host">
        <p className="host__error" role="alert">{error}</p>
      </section>
    );
  }
  if (!status) return <section className="host" aria-busy="true" />;

  const connectedIds = new Set(status.connectedDevices.map((d) => d.deviceId));
  const paired = status.pairedDevices.filter((d) => !d.revoked);

  return (
    <section className="host">
      <header className="host__head">
        <h1>{PRODUCT_NAME} is running</h1>
        <p className="host__sub">{status.pcName} is ready for your iPad.</p>
      </header>

      <section className="host__step" aria-labelledby="step-open">
        <h2 id="step-open">Open this address in Safari on the iPad</h2>
        {primaryUrl ? (
          <div className="host__address">
            <output className="host__url">{primaryUrl}</output>
            <button type="button" className="btn" onClick={copyAddress}>
              {copied ? "Copied" : "Copy address"}
            </button>
          </div>
        ) : (
          <p className="host__warn">No Wi-Fi or Ethernet connection found. Connect this PC to the same network as the iPad.</p>
        )}
        {status.urls.length > 1 && (
          <p className="host__hint">Other addresses: {status.urls.slice(1).join(", ")}</p>
        )}
      </section>

      <section className="host__step" aria-labelledby="step-code">
        <h2 id="step-code">Enter this pairing code on the iPad</h2>
        <p className="host__code" aria-label={`Pairing code ${status.pairing.code.split("").join(" ")}`}>
          {status.pairing.code.slice(0, 3)}
          <span className="host__code-gap" aria-hidden="true" />
          {status.pairing.code.slice(3)}
        </p>
        <p className="host__hint">
          Valid for {Math.max(1, Math.ceil(status.pairing.expiresIn / 60))} min. Each code works once.
        </p>
      </section>

      <section className="host__step" aria-labelledby="step-devices">
        <h2 id="step-devices">Paired devices</h2>
        {paired.length === 0 ? (
          <p className="host__hint">No devices paired yet.</p>
        ) : (
          <ul className="host__devices">
            {paired.map((d) => {
              const online = connectedIds.has(d.id);
              return (
                <li key={d.id} className="host__device">
                  <span className="led" data-tone={online ? "online" : undefined} aria-hidden="true" />
                  <span className="host__device-name">{d.name}</span>
                  <span className="host__device-state">{online ? "Connected" : "Not connected"}</span>
                  <button type="button" className="btn host__remove" onClick={() => revoke(d.id, d.name)}>
                    Remove
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </section>
  );
}
