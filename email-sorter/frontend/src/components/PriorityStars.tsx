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
