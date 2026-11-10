import { Check, Copy, Eye, EyeOff } from "lucide-react";
import { useState } from "react";

function useCopy(value: string) {
  const [copied, setCopied] = useState(false);

  function copy() {
    void navigator.clipboard?.writeText(value).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  }

  return { copied, copy };
}

const ICON_BUTTON =
  "press grid h-11 w-11 shrink-0 place-items-center rounded-[10px] border border-line text-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none";

/** One value on one line with a Copy button. `secret` hides it until revealed. */
export function CopyField({
  value,
  label = "Copy",
  secret = false,
  openPrefix = "",
}: {
  value: string;
  label?: string;
  secret?: boolean;
  /** Start of the value that stays visible while the rest is hidden. */
  openPrefix?: string;
}) {
  const { copied, copy } = useCopy(value);
  const [shown, setShown] = useState(!secret);

  return (
    <div className="flex w-full min-w-0 items-center gap-2">
      <code className="min-w-0 flex-1 break-all rounded-lg bg-surface-muted px-2.5 py-2 text-[12px] text-ink">
        {shown ? value : `${openPrefix}${"•".repeat(24)}`}
      </code>
      {secret ? (
        <button
          type="button"
          onClick={() => setShown(!shown)}
          aria-label={shown ? "Hide" : "Show"}
          className={ICON_BUTTON}
        >
          {shown ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
        </button>
      ) : null}
      <button type="button" onClick={copy} aria-label={label} className={ICON_BUTTON}>
        {copied ? <Check className="h-4 w-4 text-accent" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
      </button>
    </div>
  );
}

/** A block of code to paste, with a Copy button. */
export function CopyBlock({ value, label = "Copy" }: { value: string; label?: string }) {
  const { copied, copy } = useCopy(value);

  return (
    <div className="relative w-full min-w-0">
      <pre className="max-h-56 overflow-auto rounded-lg bg-surface-muted p-3 pr-14 text-[12px] leading-5 text-ink">
        <code>{value}</code>
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label={label}
        className={`${ICON_BUTTON} absolute top-1 right-1 bg-surface`}
      >
        {copied ? <Check className="h-4 w-4 text-accent" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
      </button>
    </div>
  );
}
