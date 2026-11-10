import { Inbox } from "lucide-react";

import { SkeletonRows } from "./Skeleton";

interface EmptyStateProps {
  onClearFilters: () => void;
  hasActiveFilters: boolean;
  loading: boolean;
  hasLoaded: boolean;
  pushed: boolean;
  onLoad: () => void;
}

const ACTION =
  "mt-1 inline-flex min-h-11 items-center rounded-[10px] bg-surface-muted px-3.5 py-1.5 text-[13px] font-medium text-ink transition-colors hover:bg-line/60 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface focus-visible:outline-none";

export function EmptyState({
  onClearFilters,
  hasActiveFilters,
  loading,
  hasLoaded,
  pushed,
  onLoad,
}: EmptyStateProps) {
  if (loading) {
    return <SkeletonRows count={5} />;
  }

  const title = hasActiveFilters
    ? "No emails match"
    : hasLoaded
      ? "Nothing in this time window"
      : pushed
        ? "Waiting for mail"
        : "Nothing loaded yet";

  const text = hasActiveFilters
    ? "Try a different search, or clear the active filters."
    : hasLoaded
      ? "Choose a longer time window to see older mail."
      : pushed
        ? "New messages appear here automatically after your Power Automate flow sends them."
        : "Load your inbox to see what needs attention.";

  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <span
        className="grid h-11 w-11 place-items-center rounded-full bg-surface-muted text-muted"
        aria-hidden="true"
      >
        <Inbox className="h-5 w-5" />
      </span>
      <div>
        <p className="text-[15px] font-semibold text-ink">{title}</p>
        <p className="mt-1.5 max-w-[34ch] text-[14px] leading-5 text-muted">
          {text}
        </p>
      </div>
      {hasActiveFilters ? (
        <button type="button" onClick={onClearFilters} className={ACTION}>
          Clear filters
        </button>
      ) : !hasLoaded ? (
        <button type="button" onClick={onLoad} className={ACTION}>
          {pushed ? "Refresh" : "Load emails"}
        </button>
      ) : null}
    </div>
  );
}
