import { useState, type FormEvent } from "react";
import { pairDevice, saveCredentials, type DeviceCredentials } from "../connection/credentials";
import { PRODUCT_NAME } from "../branding";
import "./pairing.css";

interface Props {
  onPaired: (credentials: DeviceCredentials) => void;
  notice?: string;
}

function guessDeviceName(): string {
  const ua = navigator.userAgent;
  // iPadOS reports itself as "Macintosh" but has touch points.
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "iPad";
  if (/iPhone/.test(ua)) return "iPhone";
  if (/Android/.test(ua)) return "Android tablet";
  return "Browser";
}

export function PairingScreen({ onPaired, notice }: Props) {
  const [code, setCode] = useState("");
  const [deviceName, setDeviceName] = useState(guessDeviceName);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (code.length !== 6 || busy) return;
    setBusy(true);
    setError(null);
    const result = await pairDevice(code, deviceName.trim() || "iPad");
    setBusy(false);
    if (result.ok && result.credentials) {
      saveCredentials(result.credentials);
      onPaired(result.credentials);
    } else {
      setError(result.error ?? "Pairing failed.");
      setCode("");
    }
  }

  return (
    <main className="pairing">
      <form className="pairing__panel" onSubmit={submit} noValidate>
        <h1 className="pairing__title">Pair with your PC</h1>
        <p className="pairing__lead">
          On the PC running {PRODUCT_NAME}, open <strong>localhost:{window.location.port || "80"}/pc</strong> in a
          browser. Enter the 6-digit code it shows.
        </p>
        {notice && <p className="pairing__notice">{notice}</p>}

        <label className="pairing__label" htmlFor="pair-code">
          Pairing code
        </label>
        <input
          id="pair-code"
          className="pairing__code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "pair-error" : undefined}
          autoFocus
        />

        <label className="pairing__label" htmlFor="pair-name">
          Name this device
        </label>
        <input
          id="pair-name"
          className="pairing__name"
          value={deviceName}
          maxLength={64}
          onChange={(e) => setDeviceName(e.target.value)}
        />

        <p id="pair-error" className="pairing__error" role="alert">
          {error}
        </p>

        <button className="btn btn-primary pairing__submit" type="submit" disabled={code.length !== 6 || busy}>
          {busy ? "Pairing…" : "Pair device"}
        </button>
      </form>
    </main>
  );
}
