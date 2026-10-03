import { useEffect, useState } from "react";

export function OfflineBanner({ retryInMs, onRetry }: { retryInMs?: number; onRetry: () => void }) {
  const seconds = useCountdown(retryInMs);
  return (
    <div className="offline-banner" role="alert">
      <span className="led" data-tone="error" aria-hidden="true" />
      <span className="offline-banner__text">
        Can't reach the PC.{" "}
        <span className="offline-banner__retry">{seconds > 0 ? `Retrying in ${seconds} s` : "Retrying…"}</span>
      </span>
      <button type="button" className="btn" onClick={onRetry}>
        Retry now
      </button>
    </div>
  );
}

function useCountdown(ms?: number): number {
  const [remaining, setRemaining] = useState(() => Math.ceil((ms ?? 0) / 1000));
  useEffect(() => {
    const deadline = Date.now() + (ms ?? 0);
    setRemaining(Math.ceil((ms ?? 0) / 1000));
    const timer = setInterval(() => {
      const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setRemaining(left);
      if (left === 0) clearInterval(timer);
    }, 250);
    return () => clearInterval(timer);
  }, [ms]);
  return remaining;
}
