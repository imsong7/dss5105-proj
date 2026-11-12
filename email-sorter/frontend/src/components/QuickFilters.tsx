import { Bookmark } from "lucide-react";

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
  /** Saved jobs: a last tab, shown once the student has saved one. */
  savedJobs?: { count: number; active: boolean; onSelect: () => void };
  className?: string;
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
  savedJobs,
  className = "",
}: QuickFiltersProps) {
  const showingJobs = savedJobs?.active ?? false;
  return (
    <section
      aria-label="Quick filters"
      className={`flex flex-col gap-1 border-b border-line sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2 sm:px-4 ${className}`}
    >
      <div className="-mx-4 flex gap-6 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 [&::-webkit-scrollbar]:hidden">
      {QUICK_FILTERS.map(({ key, label, dot }) => {
        const active = !showingJobs && action === key;
        const count = key === "all" ? total : counts[key];

        return (
          <button
            key={key}
            type="button"
            aria-pressed={active}
            onClick={() => onActionChange(key)}
            className={`-mb-px inline-flex h-11 shrink-0 items-center gap-2 border-b-2 text-[13px] transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
              active
                ? "border-ink font-semibold text-ink"
                : "border-transparent font-medium text-muted hover:text-ink"
            }`}
          >
            {dot ? (
              <span
                className={`h-1.5 w-1.5 rounded-full ${dot}`}
                aria-hidden="true"
              />
            ) : null}
            <span>{label}</span>
            <span className="text-[12px] text-muted tabular-nums">{count}</span>
          </button>
        );
      })}
      {savedJobs && (savedJobs.count > 0 || showingJobs) ? (
        <button
          type="button"
          aria-pressed={showingJobs}
          onClick={savedJobs.onSelect}
          className={`-mb-px inline-flex h-11 shrink-0 items-center gap-2 border-b-2 text-[13px] transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
            showingJobs
              ? "border-ink font-semibold text-ink"
              : "border-transparent font-medium text-muted hover:text-ink"
          }`}
        >
          <Bookmark className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Saved jobs</span>
          <span className="text-[12px] text-muted tabular-nums">{savedJobs.count}</span>
        </button>
      ) : null}
      </div>

      <div className={`flex items-center gap-3 sm:ml-auto ${showingJobs ? "hidden" : ""}`}>
        <p
          className="text-[12px] text-muted tabular-nums max-sm:hidden"
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
            className="inline-flex h-8 items-center rounded text-[12px] font-medium text-accent underline-offset-2 transition-colors hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page focus-visible:outline-none"
          >
            Clear filters
          </button>
        ) : null}
      </div>
    </section>
  );
}
