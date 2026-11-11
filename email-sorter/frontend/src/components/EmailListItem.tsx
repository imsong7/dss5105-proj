import { Check } from "lucide-react";

import { relativeDay, todayKey } from "../domain/calendar";
import type { InboxEmail } from "../domain/email";
import { formatListTime } from "../lib/format";
import { bodySnippet, highlight } from "../lib/highlight";
import { CategoryBadge } from "./CategoryBadge";
import { StatusBadge } from "./StatusBadge";
import { SwipeRow } from "./SwipeRow";

interface EmailListItemProps {
  email: InboxEmail;
  selected: boolean;
  query: string;
  done: boolean;
  onToggleDone: (id: string, done: boolean) => void;
  onSelect: (id: string) => void;
  registerRow: (id: string, node: HTMLButtonElement | null) => void;
}

export function EmailListItem({
  email,
  selected,
  query,
  done,
  onToggleDone,
  onSelect,
  registerRow,
}: EmailListItemProps) {
  const { sender, subject, receivedAt, classification, deadline } = email;
  // When only the body matches, show where, so the result does not look random.
  const inHeader = `${sender.name} ${sender.address} ${subject}`.toLowerCase().includes(query.trim().toLowerCase());
  const snippet = query.trim() && !inHeader ? bodySnippet(email.body, query) : "";
  const preview = snippet || email.body.replace(/\s+/g, " ").trim().slice(0, 140);
  const due = deadline && !done ? relativeDay(deadline.date, todayKey()) : null;
  const urgent = classification?.action === "needs_action" && !done;

  return (
    <li className="group relative">
      <SwipeRow
        frameClassName="rounded-none max-sm:rounded-xl"
        onSwipeRight={done ? undefined : () => onToggleDone(email.id, true)}
        rightLabel="Done"
      >
      <button
        type="button"
        ref={(node) => {
          registerRow(email.id, node);
        }}
        onClick={() => onSelect(email.id)}
        aria-current={selected ? "true" : undefined}
        className={`block w-full border-b border-b-line py-3 pr-4 pl-4 text-left transition-colors max-sm:rounded-xl max-sm:border max-sm:border-line max-sm:bg-surface ${done ? "opacity-50" : ""} focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset focus-visible:outline-none ${
          selected ? "bg-surface-muted max-sm:bg-surface max-sm:ring-1 max-sm:ring-ink/30" : "hover:bg-surface-muted/60"
        }`}
      >
        <span className="block min-w-0">
          <span data-role="sender" className="flex min-w-0 items-baseline gap-3">
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink/80">
              {highlight(sender.name, query)}
            </span>
            {selected ? <span className="sr-only">(selected)</span> : null}
            <time className="shrink-0 text-[12px] text-muted tabular-nums" dateTime={receivedAt}>
              {formatListTime(receivedAt)}
            </time>
          </span>
          <span
            data-role="subject"
            className={`mt-0.5 block truncate text-[15px] leading-[1.35] text-ink ${urgent ? "font-semibold" : "font-medium"}`}
          >
            {highlight(subject, query)}
          </span>
          {preview ? (
            <span className="mt-1 line-clamp-1 text-[13px] leading-5 text-muted">
              {highlight(preview, query)}
            </span>
          ) : null}

          <span className="mt-2 flex min-h-[18px] flex-wrap items-center gap-x-4 gap-y-1 pr-8">
            {classification ? (
              <>
                <StatusBadge action={classification.action} />
                <CategoryBadge category={classification.category} />
              </>
            ) : email.classifyError ? (
              <span title={email.classifyError} className="label text-action-now-fg">
                Could not classify
              </span>
            ) : (
              <span className="label text-muted">Not sorted yet</span>
            )}
            {due ? (
              <span
                className={`label ${due.tone === "overdue" ? "text-action-now-fg" : "text-highlight-dark"}`}
                title={`${deadline?.label} ${deadline?.date}`}
              >
                Due {due.text}
              </span>
            ) : null}
          </span>
        </span>
      </button>
      </SwipeRow>
      <button
        type="button"
        aria-label={done ? "Mark as not handled" : "Mark as handled"}
        title={done ? "Mark as not handled" : "Mark as handled"}
        onClick={() => onToggleDone(email.id, !done)}
        className={`group/done absolute right-1 bottom-0.5 grid h-9 w-9 place-items-center rounded-full transition-opacity focus-visible:opacity-100 focus-visible:outline-none max-lg:opacity-100 ${
          done ? "opacity-100" : "opacity-0 group-hover:opacity-100"
        }`}
      >
        <span
          className={`grid h-6 w-6 place-items-center rounded-full border transition-colors group-focus-visible/done:ring-2 group-focus-visible/done:ring-accent ${
            done
              ? "border-ink bg-ink text-page"
              : "border-line text-muted group-hover/done:border-ink group-hover/done:text-ink"
          }`}
          aria-hidden="true"
        >
          <Check className="h-3.5 w-3.5" strokeWidth={2.25} />
        </span>
      </button>
    </li>
  );
}
