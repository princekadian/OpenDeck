// Modal dialogs built on the native <dialog> element (focus trap, Esc, top layer).

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
  wide?: boolean;
  onSubmit?: () => void;
  /** Returning false keeps the dialog open (e.g. confirm discarding changes). */
  canClose?: () => boolean;
}

export function Modal({ title, onClose, children, footer, wide, onSubmit, canClose }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    return () => dialog.close();
  }, []);

  const requestClose = () => {
    if (!canClose || canClose()) onClose();
  };

  return (
    <dialog
      ref={ref}
      className="modal"
      data-wide={wide || undefined}
      aria-labelledby="modal-title"
      onCancel={(e) => {
        e.preventDefault();
        requestClose();
      }}
    >
      <form
        className="modal__form"
        noValidate
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          onSubmit?.();
        }}
      >
        <header className="modal__head">
          <h2 id="modal-title">{title}</h2>
          <button type="button" className="icon-btn" onClick={requestClose} aria-label="Close">
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
            </svg>
          </button>
        </header>
        <div className="modal__body">{children}</div>
        <footer className="modal__foot">{footer}</footer>
      </form>
    </dialog>
  );
}

export function ConfirmDialog({
  title,
  message,
  children,
  confirmLabel,
  danger,
  disabled,
  onConfirm,
  onClose,
}: {
  title: string;
  message?: string;
  children?: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  disabled?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      title={title}
      onClose={onClose}
      onSubmit={() => {
        if (disabled) return;
        onConfirm();
        onClose();
      }}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={danger ? "btn btn-danger" : "btn btn-primary"} disabled={disabled} autoFocus>
            {confirmLabel}
          </button>
        </>
      }
    >
      {children ?? <p className="modal__text">{message}</p>}
    </Modal>
  );
}

export function PromptDialog({
  title,
  label,
  initial,
  confirmLabel,
  onSubmit,
  onClose,
}: {
  title: string;
  label: string;
  initial: string;
  confirmLabel: string;
  onSubmit: (value: string) => Promise<string | void>;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!value.trim() || busy) {
      setError("Enter a name.");
      return;
    }
    setBusy(true);
    const problem = await onSubmit(value.trim());
    setBusy(false);
    if (problem) setError(problem);
    else onClose();
  }

  return (
    <Modal
      title={title}
      onClose={onClose}
      onSubmit={submit}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="field">
        <label className="field__label" htmlFor="prompt-input">
          {label}
        </label>
        <input
          id="prompt-input"
          className="input"
          value={value}
          maxLength={40}
          autoFocus
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
          }}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "prompt-error" : undefined}
        />
        {error && (
          <p id="prompt-error" className="field__error" role="alert">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
