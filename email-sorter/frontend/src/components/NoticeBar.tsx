import { useEffect } from "react";
import { X } from "lucide-react";

import type { Notice } from "../hooks/useInboxView";

export function NoticeBar({
  notice,
  onDismiss,
}: {
  notice: Notice | null;
  onDismiss: () => void;
}) {
  // Routine messages fade away on their own; errors wait to be read.
  useEffect(() => {
    if (!notice || notice.error) {
      return;
    }
    const timer = window.setTimeout(onDismiss, 4500);
    return () => window.clearTimeout(timer);
  }, [notice, onDismiss]);

  if (!notice) {
    return null;
  }

  return (
    <div
      role={notice.error ? "alert" : "status"}
      className={`flex items-start gap-2 rounded-[10px] px-3.5 py-2.5 text-[13px] ${
        notice.error
          ? "border border-action-now-line bg-action-now-bg text-action-now-fg"
          : "text-muted"
      }`}
    >
      <span className="flex-1">{notice.text}</span>
      {notice.error ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="grid h-6 w-6 shrink-0 place-items-center rounded hover:bg-black/5 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
