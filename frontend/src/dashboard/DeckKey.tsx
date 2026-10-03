import { memo, useEffect, useState } from "react";
import type { ButtonState, DeckButton } from "../protocol/messages";
import type { PressFeedback } from "../connection/deckStore";
import { KeyIcon } from "../icons/KeyIcon";

interface Props {
  button: DeckButton;
  state?: ButtonState;
  feedback?: PressFeedback;
  disabled: boolean;
  onPress: (buttonId: string) => void;
}

type Tone = "off" | "online" | "busy" | "error";

/** One generic renderer for every action: feedback first, then the action's reported state. */
function describe(button: DeckButton, state?: ButtonState, feedback?: PressFeedback): { tone: Tone; status: string } {
  if (!button.enabled) return { tone: "off", status: "Disabled" };
  switch (feedback?.phase) {
    case "pending":
      return { tone: "busy", status: "Working…" };
    case "armed":
      return { tone: "busy", status: feedback.message ?? "Tap again to confirm" };
    case "error":
      return { tone: "error", status: feedback.message ?? "Failed" };
    case "success": {
      const text = feedback.message && feedback.message.length <= 18 ? feedback.message : "Done";
      return { tone: "online", status: text };
    }
  }
  const detail = state?.detail;
  if (!detail) return { tone: "off", status: "" };
  return { tone: detail.tone ?? "off", status: detail.text ?? "" };
}

function stateIcon(state?: ButtonState): string | null {
  return state?.detail.icon ? `builtin:${state.detail.icon}` : null;
}

export const DeckKey = memo(function DeckKey({ button, state, feedback, disabled, onPress }: Props) {
  // Local press state gives feedback on touch-down, before the server answers.
  const [held, setHeld] = useState(false);
  const { tone, status } = describe(button, state, feedback);
  const countdown = state?.detail.countdown;
  const showCountdown = countdown && button.enabled;

  return (
    <button
      type="button"
      className="deck-key"
      data-held={held || undefined}
      data-tone={tone}
      data-off={!button.enabled || undefined}
      data-armed={feedback?.phase === "armed" || undefined}
      data-folder={button.kind === "folder" || undefined}
      disabled={disabled || !button.enabled}
      onPointerDown={() => setHeld(true)}
      onPointerUp={() => setHeld(false)}
      onPointerLeave={() => setHeld(false)}
      onPointerCancel={() => setHeld(false)}
      onClick={() => onPress(button.id)}
      aria-label={button.kind === "folder" ? `${button.label}, folder` : status ? `${button.label}, ${status}` : button.label}
      aria-busy={feedback?.phase === "pending" || undefined}
    >
      <span className="led deck-key__led" data-tone={tone === "off" ? undefined : tone} aria-hidden="true" />
      {showCountdown ? (
        <Countdown remainingMs={countdown.remainingMs} running={countdown.running} endsAt={countdown.endsAt} />
      ) : (
        <KeyIcon iconRef={stateIcon(state) ?? button.iconRef} className="deck-key__icon" />
      )}
      <span className="deck-key__label">{button.label}</span>
      <span className="deck-key__status" aria-hidden="true">
        {status}
      </span>
      {button.kind === "folder" && (
        <svg className="deck-key__folder-mark" viewBox="0 0 24 24" aria-hidden="true">
          <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </button>
  );
});

/**
 * Remaining time, animated on the device from a single state update: the PC
 * does not send a message every second. `endsAt` is fixed when the state arrives.
 */
function Countdown({ remainingMs, running, endsAt }: { remainingMs: number; running: boolean; endsAt?: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const tick = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(tick);
  }, [running]);
  const left = running && endsAt ? Math.max(0, endsAt - now) : remainingMs;
  return (
    <span className="deck-key__countdown" role="timer">
      {formatDuration(left)}
    </span>
  );
}

export function formatDuration(ms: number): string {
  const total = Math.ceil(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}
