import { Check } from "lucide-react";

import { relativeDay, todayKey } from "../domain/calendar";
import type { InboxEmail } from "../domain/email";
import type { ActionKey } from "../domain/taxonomy";
import { formatListDate } from "../lib/format";
import { bodySnippet, highlight } from "../lib/highlight";
import { CategoryBadge } from "./CategoryBadge";
import { StatusBadge } from "./StatusBadge";
import { SwipeRow } from "./SwipeRow";

const ACTION_DOT: Record<ActionKey, string> = {
  needs_action: "bg-action-now-fg",
  needs_reply: "bg-action-reply-fg",
  reminder: "bg-action-reminder-fg",
  no_immediate_action: "bg-transparent ring-1 ring-muted/50",
};

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
        className={`grid w-full grid-cols-[52px_minmax(0,1fr)] gap-x-3 border-b border-b-line py-3.5 pr-12 pl-4 text-left transition-colors max-sm:rounded-xl max-sm:border max-sm:border-line max-sm:bg-surface ${done ? "opacity-50" : ""} focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset focus-visible:outline-none ${
          selected ? "bg-surface-muted max-sm:bg-surface max-sm:ring-1 max-sm:ring-ink/30" : "hover:bg-surface-muted/60"
        }`}
      >
        <span className="flex flex-col items-start gap-2 pt-[3px]">
          <time className="text-[12px] leading-4 text-muted tabular-nums" dateTime={receivedAt}>
            {formatListDate(receivedAt)}
          </time>
          {classification ? (
            <span
              className={`h-2 w-2 rounded-full ${ACTION_DOT[classification.action]}`}
              aria-hidden="true"
            />
          ) : null}
        </span>

        <span className="min-w-0">
          <span data-role="sender" className="flex min-w-0 items-baseline gap-2">
            <span className="truncate text-[13px] font-medium text-ink/80">
              {highlight(sender.name, query)}
            </span>
            {selected ? <span className="sr-only">(selected)</span> : null}
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

          <span className="mt-2 flex min-h-[18px] flex-wrap items-center gap-x-4 gap-y-1">
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
        className={`absolute top-3 right-2 grid h-10 w-10 place-items-center rounded-full border transition-opacity hover:border-ink hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none max-lg:opacity-100 ${
          done
            ? "border-ink bg-ink text-page opacity-100"
            : "border-line text-muted opacity-0 group-hover:opacity-100"
        }`}
      >
        <Check className="h-4 w-4" aria-hidden="true" />
      </button>
    </li>
  );
}
