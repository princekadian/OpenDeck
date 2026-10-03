// Device token persistence. Safari private mode can throw on storage access.

const KEY = "msd.device.v1";

export interface DeviceCredentials {
  deviceId: string;
  deviceName: string;
  token: string;
}

export function loadCredentials(): DeviceCredentials | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DeviceCredentials;
    return typeof parsed.token === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export function saveCredentials(credentials: DeviceCredentials): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(credentials));
  } catch {
    // Not persisted: the device will need to pair again after a reload.
  }
}

export function clearCredentials(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export interface PairResult {
  ok: boolean;
  credentials?: DeviceCredentials;
  error?: string;
}

export async function pairDevice(code: string, deviceName: string): Promise<PairResult> {
  let response: Response;
  try {
    response = await fetch("/api/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, deviceName }),
    });
  } catch {
    return { ok: false, error: "Can't reach the PC. Check that both devices are on the same Wi-Fi." };
  }
  if (response.ok) {
    const body = (await response.json()) as DeviceCredentials;
    return { ok: true, credentials: body };
  }
  const body = await response.json().catch(() => null);
  const message = body?.detail?.message;
  return { ok: false, error: typeof message === "string" ? message : "Enter the 6-digit code shown on the PC." };
}
