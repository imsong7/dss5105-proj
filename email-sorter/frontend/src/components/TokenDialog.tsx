import { useEffect, useRef, useState } from "react";

interface TokenDialogProps {
  open: boolean;
  initial: string;
  onSubmit: (token: string) => void;
  onClose: () => void;
  /** Present when the student may switch to their Power Automate flow. */
  onSwitchSource?: () => void;
}

export function TokenDialog({ open, initial, onSubmit, onClose, onSwitchSource }: TokenDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState(initial);
  const [error, setError] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) {
      return;
    }

    if (open && !dialog.open) {
      setValue(initial);
      setError(false);
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, initial]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="token-title"
      className="m-auto w-[min(460px,calc(100%-32px))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-[0_24px_60px_rgba(0,0,0,0.25)] backdrop:bg-black/40"
    >
      <form
        method="dialog"
        className="p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (!value.trim()) {
            setError(true);
            return;
          }
          onSubmit(value.trim());
        }}
      >
        <h2 id="token-title" className="text-[17px] font-semibold">
          Connect your Outlook mailbox
        </h2>
        <p className="mt-1.5 text-[14px] leading-5 text-muted">
          Open{" "}
          <a
            className="text-accent underline underline-offset-2"
            href="https://developer.microsoft.com/en-us/graph/graph-explorer"
            target="_blank"
            rel="noopener noreferrer"
          >
            Graph Explorer
          </a>
          , sign in, and copy the access token. It needs <code>Mail.Read</code>{" "}
          and stays in this tab. Tokens expire after about an hour.
        </p>
        <label htmlFor="graph-token" className="mt-4 block text-[13px] font-medium">
          Access token
        </label>
        <textarea
          id="graph-token"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setError(false);
          }}
          spellCheck={false}
          autoComplete="off"
          placeholder="Paste a token from Graph Explorer"
          className="mt-1.5 min-h-24 w-full rounded-[10px] border border-line bg-surface p-3 font-mono text-[13px] focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
        />
        {error ? (
          <p role="alert" className="mt-1.5 text-[13px] text-action-now-fg">
            Paste a token first.
          </p>
        ) : null}
        {onSwitchSource ? (
          <p className="mt-3 text-[13px] leading-5 text-muted">
            Tired of pasting a token?{" "}
            <button
              type="button"
              onClick={onSwitchSource}
              className="font-medium text-accent underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              Use Power Automate instead
            </button>
            . It takes a few minutes once, then sends your mail on its own.
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
            className="min-h-11 rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none"
          >
            Load emails
          </button>
        </div>
      </form>
    </dialog>
  );
}
