import { todayKey } from "../domain/calendar";
import type { InboxEmail } from "../domain/email";
import { emailDayKey, formatDayHeading } from "../lib/format";
import { EmailListItem } from "./EmailListItem";
import { EmptyState } from "./EmptyState";

interface EmailListProps {
  emails: readonly InboxEmail[];
  selectedId: string | null;
  query: string;
  isDone: (id: string) => boolean;
  onToggleDone: (id: string, done: boolean) => void;
  onSelect: (id: string) => void;
  onClearFilters: () => void;
  hasActiveFilters: boolean;
  loading: boolean;
  hasLoaded: boolean;
  pushed: boolean;
  onLoad: () => void;
  registerRow: (id: string, node: HTMLButtonElement | null) => void;
  className?: string;
}

interface DayGroup {
  key: string;
  emails: InboxEmail[];
}

/** Consecutive emails from the same Singapore day, kept in the current sort order. */
function groupByDay(emails: readonly InboxEmail[]): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const email of emails) {
    const key = emailDayKey(email.receivedAt);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.emails.push(email);
    else groups.push({ key, emails: [email] });
  }
  return groups;
}

export function EmailList({
  emails,
  selectedId,
  query,
  isDone,
  onToggleDone,
  onSelect,
  onClearFilters,
  hasActiveFilters,
  loading,
  hasLoaded,
  pushed,
  onLoad,
  registerRow,
  className = "",
}: EmailListProps) {
  const today = todayKey();
  return (
    <section
      aria-label="Email list"
      className={`w-full flex-col bg-surface lg:w-[440px] lg:shrink-0 lg:overflow-y-auto lg:border-r lg:border-line inbox-scroll xl:w-[470px] ${className}`}
    >
      {emails.length === 0 ? (
        <EmptyState
          onClearFilters={onClearFilters}
          hasActiveFilters={hasActiveFilters}
          loading={loading}
          hasLoaded={hasLoaded}
          pushed={pushed}
          onLoad={onLoad}
        />
      ) : (
        <div className="stagger">
          {groupByDay(emails).map((group) => {
            const heading = formatDayHeading(group.key, today);
            return (
              <section key={group.key} aria-label={heading}>
                <h3 className="sticky top-0 z-10 flex h-7 items-center border-b border-line bg-surface/95 px-4 text-[12px] font-medium text-muted backdrop-blur max-sm:mb-2 max-sm:border-b-0 max-sm:bg-page/95 max-sm:px-1">
                  {heading}
                </h3>
                <ul className="max-sm:mb-3 max-sm:flex max-sm:flex-col max-sm:gap-2.5">
                  {group.emails.map((email) => (
                    <EmailListItem
                      key={email.id}
                      email={email}
                      selected={email.id === selectedId}
                      query={query}
                      done={isDone(email.id)}
                      onToggleDone={onToggleDone}
                      onSelect={onSelect}
                      registerRow={registerRow}
                    />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}
