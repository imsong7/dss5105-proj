import { Check } from "lucide-react";

import type { ActionFilter } from "../domain/email";
import type { ActionKey } from "../domain/taxonomy";

interface QuickFiltersProps {
  action: ActionFilter;
  onActionChange: (action: ActionFilter) => void;
  counts: Record<ActionKey, number>;
  total: number;
  visibleCount: number;
  hasActiveFilters: boolean;
  onClearFilters: () => void;
}

const QUICK_FILTERS = [
  { key: "all", label: "All mail", dot: "" },
  {
    key: "needs_action",
    label: "Needs action",
    dot: "bg-action-now-fg",
  },
  {
    key: "needs_reply",
    label: "Needs reply",
    dot: "bg-action-reply-fg",
  },
  {
    key: "reminder",
    label: "Reminder",
    dot: "bg-action-reminder-fg",
  },
] as const;

export function QuickFilters({
  action,
  onActionChange,
  counts,
  total,
  visibleCount,
  hasActiveFilters,
  onClearFilters,
}: QuickFiltersProps) {
  return (
    <section
      aria-label="Quick filters"
      className="flex flex-col gap-1 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2 sm:gap-y-2"
    >
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0 [&::-webkit-scrollbar]:hidden">
      {QUICK_FILTERS.map(({ key, label, dot }) => {
        const active = action === key;
        const count = key === "all" ? total : counts[key];

        return (
          <button
            key={key}
            type="button"
            aria-pressed={active}
            onClick={() => onActionChange(key)}
            className={`inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-xl border px-3 py-1.5 text-[13px] font-semibold transition-all focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page focus-visible:outline-none ${
              active
                ? "border-accent/25 bg-accent-soft text-accent-dark shadow-sm"
                : "border-transparent bg-surface/65 text-ink/70 hover:border-line hover:bg-surface hover:text-ink"
            }`}
          >
            {active ? (
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
            ) : dot ? (
              <span
                className={`h-1.5 w-1.5 rounded-full ${dot}`}
                aria-hidden="true"
              />
            ) : null}
            <span>{label}</span>
            <span
              className={`text-[12px] font-medium tabular-nums ${
                active ? "text-accent-dark" : "text-muted"
              }`}
            >
              {count}
            </span>
          </button>
        );
      })}
      </div>

      <div className="flex items-center gap-2.5 sm:ml-auto">
        <p
          className="text-[13px] text-muted tabular-nums max-sm:hidden"
          aria-live="polite"
          aria-atomic="true"
        >
          {visibleCount === total
            ? `${total} messages`
            : `${visibleCount} of ${total} messages`}
        </p>
        {hasActiveFilters ? (
          <button
            type="button"
            onClick={onClearFilters}
            className="inline-flex min-h-11 items-center rounded text-xs font-medium text-accent underline-offset-2 transition-colors hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page focus-visible:outline-none"
          >
            Clear filters
          </button>
        ) : null}
      </div>
    </section>
  );
}
