import { CalendarClock, Check } from "lucide-react";

import { relativeDay, todayKey } from "../domain/calendar";
import type { InboxEmail } from "../domain/email";
import { senderInitials } from "../domain/inbox";
import { formatListDate } from "../lib/format";
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
  const preview = snippet || email.body.replace(/\s+/g, " ").trim().slice(0, 96);
  const due = deadline && !done ? relativeDay(deadline.date, todayKey()) : null;

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
        className={`press relative block w-full border-b border-b-line/70 px-4 py-3.5 pr-12 text-left transition-colors max-sm:rounded-2xl max-sm:border max-sm:border-line max-sm:bg-surface max-sm:py-4 max-sm:shadow-[0_2px_8px_rgba(16,24,40,0.05)] ${done ? "opacity-55" : ""} focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset focus-visible:outline-none ${
          selected
            ? "bg-accent-soft/80 before:absolute before:inset-y-3 before:left-0 before:w-[3px] before:rounded-r-full before:bg-accent max-sm:bg-surface max-sm:ring-1 max-sm:ring-accent/30"
            : "hover:bg-surface-muted/70"
        }`}
      >
        <span className="flex items-start gap-3">
          <span
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface-muted text-[12px] font-bold text-accent ring-1 ring-line/70"
            aria-hidden="true"
          >
            {senderInitials(sender.name)}
          </span>
          <span className="min-w-0 flex-1">
            <span
              data-role="subject"
              className="block truncate text-[14px] leading-5 font-bold tracking-[-0.01em] text-ink"
            >
              {highlight(subject, query)}
              {selected ? <span className="sr-only"> (selected)</span> : null}
            </span>
            <span data-role="sender" className="mt-0.5 block truncate text-[12px] font-medium text-muted">
              {highlight(sender.name, query)}
            </span>
          </span>
          <time className="shrink-0 pt-0.5 text-[11px] font-medium text-muted" dateTime={receivedAt}>
            {formatListDate(receivedAt)}
          </time>
        </span>

        {preview ? (
          <span className="mt-2 block truncate pl-12 text-[12px] leading-5 text-muted/90">{highlight(preview, query)}</span>
        ) : null}

        <span className="mt-2 flex min-h-[22px] flex-wrap items-center gap-2 pl-12">
          {classification ? (
            <>
              <StatusBadge action={classification.action} />
              <CategoryBadge category={classification.category} />
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
          {due ? (
            <span
              className={`ml-auto inline-flex items-center gap-1 text-[11px] font-bold ${
                due.tone === "overdue" ? "text-action-now-fg" : "text-highlight-dark"
              }`}
              title={`${deadline?.label} ${deadline?.date}`}
            >
              <CalendarClock className="h-3 w-3" aria-hidden="true" />
              Due {due.text.toLowerCase()}
            </span>
          ) : null}
        </span>
      </button>
      </SwipeRow>
      <button
        type="button"
        aria-label={done ? "Mark as not handled" : "Mark as handled"}
        title={done ? "Mark as not handled" : "Mark as handled"}
        onClick={() => onToggleDone(email.id, !done)}
        className={`absolute right-1.5 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center rounded-xl text-muted transition-opacity hover:bg-surface-muted hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none max-lg:opacity-100 ${
          done ? "opacity-100 text-accent" : "opacity-0 group-hover:opacity-100"
        }`}
      >
        <Check className="h-4 w-4" aria-hidden="true" />
      </button>
    </li>
  );
}
