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
      className="flex flex-col gap-1 border-b border-line sm:flex-row sm:flex-wrap sm:items-end sm:gap-x-2"
    >
      <div className="-mx-4 flex gap-6 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 [&::-webkit-scrollbar]:hidden">
      {QUICK_FILTERS.map(({ key, label, dot }) => {
        const active = action === key;
        const count = key === "all" ? total : counts[key];

        return (
          <button
            key={key}
            type="button"
            aria-pressed={active}
            onClick={() => onActionChange(key)}
            className={`-mb-px inline-flex min-h-11 shrink-0 items-center gap-2 border-b-2 text-[14px] transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
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
      </div>

      <div className="flex items-center gap-2.5 sm:ml-auto sm:pb-1">
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
            className="inline-flex min-h-11 items-center rounded text-xs font-medium text-accent underline-offset-2 transition-colors hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page focus-visible:outline-none"
          >
            Clear filters
          </button>
        ) : null}
      </div>
    </section>
  );
}
