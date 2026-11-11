import type { InboxEmail } from "../domain/email";
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
        <ul className="stagger max-sm:flex max-sm:flex-col max-sm:gap-2.5">
          {emails.map((email) => (
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
      )}
    </section>
  );
}
