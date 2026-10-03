// Sends dashboard crashes to the PC log. iPad Safari has no console the user can easily read,
// so without this an iPad-only failure is invisible.

let reported = 0;
const MAX_REPORTS_PER_PAGE = 5;

export function reportClientError(error: unknown, context = ""): void {
  if (reported >= MAX_REPORTS_PER_PAGE) return;
  reported += 1;
  const err = error instanceof Error ? error : new Error(String(error));
  const body = JSON.stringify({
    message: `${err.name}: ${err.message}`.slice(0, 500),
    detail: `${context}\n${err.stack ?? ""}`.slice(0, 4000),
  });
  try {
    void fetch("/api/client-errors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* reporting must never throw */
  }
}

export function installGlobalErrorReporting(): void {
  window.addEventListener("error", (event) => reportClientError(event.error ?? event.message, "window.onerror"));
  window.addEventListener("unhandledrejection", (event) => reportClientError(event.reason, "unhandledrejection"));
}

/** Connection tracing is opt-in: open the dashboard with `?debug` in the URL. */
export function connectionTraceEnabled(): boolean {
  try {
    return new URLSearchParams(window.location.search).has("debug");
  } catch {
    return false;
  }
}

const traceStart = Date.now();

export function reportTrace(event: string): void {
  const body = JSON.stringify({
    level: "trace",
    message: `+${Date.now() - traceStart}ms ${event} visibility=${document.visibilityState}`.slice(0, 500),
  });
  try {
    void fetch("/api/client-errors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* tracing must never throw */
  }
}
