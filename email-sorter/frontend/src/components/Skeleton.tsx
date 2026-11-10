/** Grey placeholder rows shown while mail loads. */
export function SkeletonRows({ count = 4, withAvatar = true }: { count?: number; withAvatar?: boolean }) {
  return (
    <div role="status" aria-label="Loading" className="animate-pulse">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="flex items-center gap-3 border-b border-b-line/70 px-4 py-3.5">
          {withAvatar ? <span className="h-8 w-8 shrink-0 rounded-full bg-surface-muted" /> : null}
          <span className="flex-1 space-y-2">
            <span className="block h-3 w-2/5 rounded bg-surface-muted" />
            <span className="block h-3 w-4/5 rounded bg-surface-muted" />
          </span>
        </div>
      ))}
    </div>
  );
}
