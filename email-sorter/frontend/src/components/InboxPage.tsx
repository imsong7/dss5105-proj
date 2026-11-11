import { useCallback, useEffect, useRef } from "react";

import type { InboxView } from "../hooks/useInboxView";
import type { ItemStates } from "../hooks/useItemStates";
import { EmailDetail } from "./EmailDetail";
import { EmailList } from "./EmailList";
import { MobileHero } from "./MobileHero";
import { InboxToolbar } from "./InboxToolbar";
import { NoticeBar } from "./NoticeBar";
import { QuickFilters } from "./QuickFilters";

interface InboxPageProps {
  view: InboxView;
  states: ItemStates;
  /** Set when the email was opened from another screen; Back goes there. */
  returnLabel?: string;
  onReturn?: () => void;
}

export function InboxPage({ view, states, returnLabel, onReturn }: InboxPageProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const rowRefs = useRef(new Map<string, HTMLButtonElement>());

  const showMobileDetail =
    view.mobileDetailOpen && view.selectedEmail !== null;

  useEffect(() => {
    if (showMobileDetail) {
      headingRef.current?.focus();
    }
  }, [showMobileDetail, view.selectedEmail?.id]);

  // The phone's back gesture or button closes the open email, not the app.
  const closeDetail = useRef(() => {});
  closeDetail.current = () => {
    if (onReturn) {
      onReturn();
    } else {
      view.closeMobileDetail();
    }
  };
  useEffect(() => {
    if (!showMobileDetail) {
      return;
    }
    window.history.pushState({ inboxDetail: true }, "");
    const onPop = () => closeDetail.current();
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      if (window.history.state?.inboxDetail) {
        window.history.back();
      }
    };
  }, [showMobileDetail]);

  // Keep the keyboard-selected row visible.
  useEffect(() => {
    if (view.selectedId) {
      rowRefs.current.get(view.selectedId)?.scrollIntoView({ block: "nearest" });
    }
  }, [view.selectedId]);

  // Opening an email from the calendar should land on its detail heading.
  useEffect(() => {
    if (view.detailFocusNonce > 0) {
      headingRef.current?.focus();
    }
  }, [view.detailFocusNonce]);

  const registerRow = useCallback(
    (id: string, node: HTMLButtonElement | null) => {
      if (node) {
        rowRefs.current.set(id, node);
      } else {
        rowRefs.current.delete(id);
      }
    },
    [],
  );

  function handleBack() {
    if (onReturn) {
      onReturn();
      return;
    }

    const id = view.selectedEmail?.id ?? null;
    view.closeMobileDetail();

    window.requestAnimationFrame(() => {
      if (id) {
        rowRefs.current.get(id)?.focus();
      }
    });
  }

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-3 px-4 py-4 sm:px-6 lg:min-h-0 lg:px-8 lg:py-4">
      <h1 className="sr-only max-sm:hidden">Inbox</h1>
      {!showMobileDetail ? (
        <MobileHero
          title="Inbox"
          subtitle={
            view.hasLoaded
              ? `${view.total} message${view.total === 1 ? "" : "s"}${
                  view.counts.needs_action ? ` · ${view.counts.needs_action} need action` : ""
                }`
              : "Load your mail to begin"
          }
        />
      ) : null}

      {/* Wide screens: filter tabs and search share one row; narrower ones stack them. */}
      <div className={`flex shrink-0 flex-col gap-2.5 ${showMobileDetail ? "max-lg:hidden" : ""}`}>
        <div className="flex flex-col gap-2.5 min-[1400px]:flex-row min-[1400px]:items-end min-[1400px]:gap-6">
          <div className="order-2 min-w-0 min-[1400px]:order-1 min-[1400px]:flex-1">
            <QuickFilters
              action={view.action}
              onActionChange={view.setAction}
              counts={view.counts}
              total={view.total}
              visibleCount={view.visibleCount}
              hasActiveFilters={view.hasActiveFilters}
              onClearFilters={view.clearFilters}
            />
          </div>
          <div className="order-1 min-[1400px]:order-2 min-[1400px]:w-[760px] min-[1400px]:shrink-0">
            <InboxToolbar view={view} />
          </div>
        </div>
        <NoticeBar notice={view.notice} onDismiss={view.dismissNotice} />
      </div>

      <div
        className={`flex min-h-0 flex-1 overflow-hidden rounded-md border border-line bg-surface ${
          showMobileDetail ? "" : "max-sm:overflow-visible max-sm:border-0 max-sm:bg-transparent max-sm:shadow-none"
        }`}
      >
        <EmailList
          emails={view.visibleEmails}
          selectedId={view.selectedId}
          query={view.query}
          isDone={states.isDone}
          onToggleDone={(id, done) => void states.setDone(id, done)}
          onSelect={view.selectEmail}
          onClearFilters={view.clearFilters}
          hasActiveFilters={view.hasActiveFilters}
          loading={view.loading}
          hasLoaded={view.hasLoaded}
          pushed={view.session.provider === "powerautomate"}
          onLoad={() => void view.load({ announce: true })}
          registerRow={registerRow}
          className={showMobileDetail ? "hidden lg:flex" : "flex"}
        />
        <EmailDetail
          email={view.selectedEmail}
          onBack={handleBack}
          backLabel={returnLabel}
          onCorrect={view.correct}
          onUndoCorrection={view.undoCorrection}
          onRemoveRule={view.removeRule}
          onDraftReply={view.draftReply}
          onSendReply={view.sendReply}
          headingRef={headingRef}
          className={showMobileDetail ? "flex" : "hidden lg:flex"}
        />
      </div>
    </main>
  );
}
