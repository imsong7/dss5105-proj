import { useEffect, useRef, useState } from "react";

interface NameDialogProps {
  open: boolean;
  current: string;
  onSave: (name: string) => Promise<void>;
  onClose: () => void;
}

export function NameDialog({ open, current, onSave, onClose }: NameDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState(current);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) {
      return;
    }

    if (open && !dialog.open) {
      setValue(current);
      setError(null);
      setBusy(false);
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, current]);

  async function submit() {
    setBusy(true);
    setError(null);

    try {
      await onSave(value);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the name.");
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="name-title"
      className="m-auto w-[min(380px,calc(100%-32px))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-[0_24px_60px_rgba(0,0,0,0.25)] backdrop:bg-black/40"
    >
      <form
        method="dialog"
        className="p-5"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <h2 id="name-title" className="text-[17px] font-semibold">
          What should we call you?
        </h2>
        <label htmlFor="display-name" className="mt-3 block text-[13px] font-medium">
          Name
        </label>
        <input
          id="display-name"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          maxLength={40}
          autoComplete="given-name"
          placeholder="e.g. Soo"
          className="mt-1.5 h-11 w-full rounded-[10px] border border-line bg-surface px-3 text-[14px] text-ink focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
        />
        <p className="mt-1.5 text-[13px] text-muted">
          Shown in the greeting on Today. Leave it empty to use your email.
        </p>
        {error ? (
          <p role="alert" className="mt-2 text-[13px] text-action-now-fg">
            {error}
          </p>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 rounded-[10px] px-4 text-[14px] font-medium text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="min-h-11 rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
