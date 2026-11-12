import { useState } from "react";

import type { EmailPriority } from "../domain/email";

interface PriorityStarsProps {
  priority: EmailPriority;
  /** "compact" is the narrow, fixed-width version used in the email list. */
  size?: "default" | "compact";
}

/** What the priority means in words, for tooltips and screen readers. */
function describe({ stars, keyPoint, suspicious, notes }: EmailPriority): string {
  return [`Priority ${stars} of 5`, keyPoint, ...notes, suspicious ? "Possible phishing" : ""]
    .filter(Boolean)
    .join(" · ");
}

/** Priority 1 to 5 as five short segments, filled in the calendar's NUS orange. */
export function PriorityStars({ priority, size = "default" }: PriorityStarsProps) {
  const { stars, suspicious } = priority;
  const title = describe(priority);
  const compact = size === "compact";
  return (
    <span
      className="inline-flex items-center gap-2 text-[12px] text-muted"
      title={title}
      role="img"
      aria-label={`Priority ${stars} of 5${suspicious ? ", possible phishing" : ""}`}
    >
      <span className={`inline-flex items-center ${compact ? "gap-px" : "gap-[2px]"}`} aria-hidden="true">
        {[1, 2, 3, 4, 5].map((dot) => (
          <span
            key={dot}
            className={`${compact ? "h-1 w-[5px]" : "h-[5px] w-3"} rounded-[1px] ${dot <= stars ? "bg-highlight" : "bg-line"}`}
          />
        ))}
      </span>
      {suspicious && !compact ? <span className="label text-action-now-fg">Suspicious</span> : null}
    </span>
  );
}

interface PriorityEditorProps {
  priority: EmailPriority | undefined;
  /** Stars 1 to 5, or null to go back to the model's rating. Throws with a readable message. */
  onChange: (stars: number | null) => Promise<void>;
}

/**
 * Five segments the student can press to set the priority by hand. The same orange
 * as the read-only bar; "Reset" goes back to what the model rated (or clears it).
 */
export function PriorityEditor({ priority, onChange }: PriorityEditorProps) {
  const [hover, setHover] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stars = priority?.stars ?? 0;
  const shown = hover || stars;

  async function choose(next: number | null) {
    if (busy || next === stars) return;
    setBusy(true);
    setError(null);
    try {
      await onChange(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the priority.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-x-2">
      <span
        role="radiogroup"
        aria-label="Priority"
        title={priority ? describe(priority) : "Not rated yet. Press a bar to set the priority."}
        className="inline-flex items-center"
        onMouseLeave={() => setHover(0)}
      >
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={n === stars}
            aria-label={`Priority ${n} of 5`}
            disabled={busy}
            onMouseEnter={() => setHover(n)}
            onFocus={() => setHover(n)}
            onBlur={() => setHover(0)}
            onClick={() => void choose(n)}
            className="grid h-8 w-[18px] place-items-center rounded focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:cursor-wait sm:h-6"
          >
            <span className={`h-[6px] w-3 rounded-[1px] ${n <= shown ? "bg-highlight" : "bg-line"}`} />
          </button>
        ))}
      </span>
      {priority?.suspicious ? <span className="label text-action-now-fg">Suspicious</span> : null}
      {priority?.manual ? (
        <>
          <span className="text-[12px] text-muted">edited</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => void choose(null)}
            className="inline-flex min-h-8 items-center rounded-lg px-1.5 text-[12px] text-muted underline-offset-2 hover:text-ink hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          >
            {priority.modelStars === undefined ? "Clear" : "Reset"}
          </button>
        </>
      ) : null}
      {error ? (
        <span role="alert" className="text-[12px] text-action-now-fg">
          {error}
        </span>
      ) : null}
    </span>
  );
}
