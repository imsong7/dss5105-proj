import { Check } from "lucide-react";

import { relativeDay, todayKey } from "../domain/calendar";
import type { InboxEmail } from "../domain/email";
import { senderInitials } from "../domain/inbox";
import { formatListDate } from "../lib/format";
import { CONTENT_CATEGORIES } from "../domain/taxonomy";
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

  return (
    <li className="group relative">
      <SwipeRow
        frameClassName="rounded-none max-sm:rounded-2xl"
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
        className={`press block w-full border-b border-b-line/70 px-4 py-3 text-left transition-colors max-sm:rounded-2xl max-sm:border max-sm:border-line max-sm:bg-surface max-sm:py-3.5 max-sm:shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${done ? "opacity-55" : ""} focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset focus-visible:outline-none ${
          selected
            ? "bg-accent-soft max-sm:bg-surface max-sm:ring-1 max-sm:ring-accent/30"
            : "hover:bg-surface-muted/60"
        }`}
      >
        <span className="flex items-center gap-3">
          <span
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-muted text-[12px] font-semibold text-ink/60"
            aria-hidden="true"
          >
            {senderInitials(sender.name)}
          </span>
          <span
            data-role="sender"
            className="min-w-0 flex-1 truncate text-[14px] font-semibold text-ink"
          >
            {highlight(sender.name, query)}
            {selected ? <span className="sr-only"> (selected)</span> : null}
          </span>
          {deadline && !done ? (
            <span
              className={`shrink-0 text-[12px] font-semibold ${
                relativeDay(deadline.date, todayKey()).tone === "overdue"
                  ? "text-action-now-fg"
                  : "text-highlight-dark"
              }`}
              title={`${deadline.label} ${deadline.date}`}
            >
              Due {relativeDay(deadline.date, todayKey()).text.toLowerCase()}
            </span>
          ) : (
            <time
              className="shrink-0 text-[12px] text-muted"
              dateTime={receivedAt}
            >
              {formatListDate(receivedAt)}
            </time>
          )}
        </span>

        <span
          data-role="subject"
          className="mt-1.5 block truncate text-[14px] leading-5 font-medium text-ink"
        >
          {highlight(subject, query)}
        </span>
        {snippet ? (
          <span className="mt-1 block truncate text-[13px] text-muted">{highlight(snippet, query)}</span>
        ) : null}

        <span className="mt-1.5 flex min-h-[22px] flex-wrap items-center gap-2">
          {classification ? (
            <>
              <StatusBadge action={classification.action} />
              <span className="text-[12px] text-muted max-sm:hidden">
                {CONTENT_CATEGORIES[classification.category]}
              </span>
              <span className="sm:hidden">
                <CategoryBadge category={classification.category} />
              </span>
            </>
          ) : email.classifyError ? (
            <span
              title={email.classifyError}
              className="inline-flex items-center rounded-full border border-action-now-line bg-action-now-bg px-2 py-[3px] text-[11px] font-semibold text-action-now-fg"
            >
              Could not classify
            </span>
          ) : (
            <span className="text-[12px] text-muted">Not sorted yet</span>
          )}
        </span>
      </button>
      </SwipeRow>
      <button
        type="button"
        aria-label={done ? "Mark as not handled" : "Mark as handled"}
        title={done ? "Mark as not handled" : "Mark as handled"}
        onClick={() => onToggleDone(email.id, !done)}
        className={`absolute right-2 bottom-1.5 grid h-11 w-11 place-items-center rounded-[10px] text-muted transition-opacity hover:bg-surface-muted hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none max-lg:opacity-100 ${
          done ? "opacity-100 text-accent" : "opacity-0 group-hover:opacity-100"
        }`}
      >
        <Check className="h-4 w-4" aria-hidden="true" />
      </button>
    </li>
  );
}
