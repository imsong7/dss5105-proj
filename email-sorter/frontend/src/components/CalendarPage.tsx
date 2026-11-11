import { useState } from "react";
import { ChevronDown, Loader2, Plus, SlidersHorizontal } from "lucide-react";

import type { PersonalEventDraft } from "../domain/calendar";
import type { CalendarView } from "../hooks/useCalendarView";
import { AgendaView } from "./AgendaView";
import { EventDialog } from "./EventDialog";
import { FeedDialog } from "./FeedDialog";
import { Popover } from "./Popover";
import type { EventDialogTarget } from "./EventDialog";
import { MobileHero } from "./MobileHero";
import { BottomSheet, usePhone } from "./BottomSheet";
import { CalendarDayPanel } from "./CalendarDayPanel";
import { CalendarMonth } from "./CalendarMonth";

interface CalendarPageProps {
  /** Mail is still loading, so the calendar may fill in shortly. */
  loading?: boolean;
  view: CalendarView;
  onOpenEmail: (id: string) => void;
  onSaveEvent: (draft: PersonalEventDraft, id?: string) => Promise<void>;
  onDeleteEvent: (id: string) => Promise<void>;
}

const MODE_KEY = "inbox-sorter.calendarMode";

/** Phones start on the agenda; desktops on the month grid. */
function readMode(): "month" | "agenda" {
  try {
    const stored = window.localStorage.getItem(MODE_KEY);
    if (stored === "month" || stored === "agenda") {
      return stored;
    }
  } catch {
    // Fall through to the screen-size default.
  }
  return window.matchMedia("(min-width: 1024px)").matches ? "month" : "agenda";
}

export function CalendarPage({
  view,
  onOpenEmail,
  onSaveEvent,
  onDeleteEvent,
  loading = false,
}: CalendarPageProps) {
  const [dialog, setDialog] = useState<EventDialogTarget>(null);
  const [mode, setMode] = useState<"month" | "agenda">(readMode);
  const [feedOpen, setFeedOpen] = useState(false);
  const [daySheet, setDaySheet] = useState(false);
  const phone = usePhone();

  function chooseMode(next: "month" | "agenda") {
    setMode(next);
    try {
      window.localStorage.setItem(MODE_KEY, next);
    } catch {
      // The choice simply will not be remembered.
    }
  }

  return (
    <div className="flex flex-1 flex-col lg:min-h-0 lg:overflow-y-auto">
    <main className="mx-auto flex w-full max-w-[1360px] flex-1 flex-col gap-4 px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
      <h1 className="sr-only max-sm:hidden">Calendar</h1>
      <MobileHero
        title="Calendar"
        subtitle={
          loading
            ? "Loading your mail…"
            : `${view.monthCount} date${view.monthCount === 1 ? "" : "s"} this month`
        }
      />

      {loading ? (
        <p role="status" className="flex items-center gap-2 text-[13px] text-accent max-sm:hidden">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading your mail… dates will appear as it arrives.
        </p>
      ) : null}

      <div className="flex items-center gap-2 sm:gap-3">
        <button
          type="button"
          onClick={() => setDialog({ mode: "new", date: view.selectedDate })}
          className="inline-flex h-11 items-center gap-1.5 rounded-lg bg-accent px-3.5 text-[13px] font-semibold sm:h-9 text-white transition-colors max-sm:hidden hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page focus-visible:outline-none"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          Add event
        </button>
        <div
          role="group"
          aria-label="Calendar layout"
          className="inline-flex rounded-lg bg-surface-muted p-0.5 max-sm:flex-1"
        >
          {(["month", "agenda"] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={mode === option}
              onClick={() => chooseMode(option)}
              className={`h-10 rounded-md px-3.5 text-[13px] capitalize sm:h-8 max-sm:flex-1 transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
                mode === option
                  ? "bg-surface font-semibold text-accent shadow-[0_1px_3px_rgba(0,0,0,0.10)]"
                  : "font-medium text-muted hover:text-ink"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
        <Popover
          ariaLabel="More calendar options"
          align="right"
          buttonClassName="max-sm:w-11 max-sm:justify-center max-sm:px-0"
          label={
            <>
              <SlidersHorizontal className="h-4 w-4 sm:hidden" aria-hidden="true" />
              <span className="max-sm:sr-only">Show</span>
              <ChevronDown className="h-3.5 w-3.5 text-muted max-sm:hidden" aria-hidden="true" />
            </>
          }
        >
          {(close) => (
            <div className="flex flex-col">
              {view.hasAcademic ? (
                <button
                  type="button"
                  role="switch"
                  aria-checked={view.showAcademic}
                  onClick={() => view.setShowAcademic(!view.showAcademic)}
                  className="flex min-h-11 w-full items-center justify-between gap-3 rounded-lg px-2.5 text-left text-[14px] text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                >
                  NUS calendar
                  <span
                    aria-hidden="true"
                    className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                      view.showAcademic ? "bg-accent" : "bg-line"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
                        view.showAcademic ? "left-[18px]" : "left-0.5"
                      }`}
                    />
                  </span>
                </button>
              ) : null}

              <button
                type="button"
                onClick={() => {
                  setFeedOpen(true);
                  close();
                }}
                className="flex min-h-11 w-full items-center rounded-lg px-2.5 text-left text-[14px] text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
              >
                Add to Google or Apple Calendar
              </button>
            </div>
          )}
        </Popover>
      </div>

      {mode === "agenda" ? (
        <AgendaView
          deadlines={view.deadlines}
          academic={view.academicVisible}
          today={view.todayKey}
          onOpenEmail={onOpenEmail}
          onEditEvent={(event) => setDialog({ mode: "edit", event })}
        />
      ) : (
      <>
      <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-start">
        <CalendarMonth
          month={view.month}
          cells={view.cells}
          deadlinesByDate={view.deadlinesByDate}
          academicMarkers={view.academicMarkers}
          selectedDate={view.selectedDate}
          todayKey={view.todayKey}
          monthCount={view.monthCount}
          onSelectDate={(date) => {
            view.selectDate(date);
            setDaySheet(true);
          }}
          onAddOnDate={(date) => setDialog({ mode: "new", date })}
          onPrevMonth={() => view.goToMonth(-1)}
          onNextMonth={() => view.goToMonth(1)}
          onToday={view.goToToday}
        />

        <CalendarDayPanel
          selectedDate={view.selectedDate}
          selectedDeadlines={view.selectedDeadlines}
          upcoming={view.upcoming}
          academic={view.selectedAcademic}
          upcomingAcademic={view.upcomingAcademicEvents}
          onSelectDate={view.selectDate}
          onOpenEmail={onOpenEmail}
          onAddEvent={() => setDialog({ mode: "new", date: view.selectedDate })}
          onEditEvent={(event) => setDialog({ mode: "edit", event })}
          className="min-w-0 max-sm:hidden"
        />
      </div>
      <BottomSheet open={phone && daySheet} label="Selected day" onClose={() => setDaySheet(false)}>
        <CalendarDayPanel
          selectedDate={view.selectedDate}
          selectedDeadlines={view.selectedDeadlines}
          upcoming={view.upcoming}
          academic={view.selectedAcademic}
          upcomingAcademic={view.upcomingAcademicEvents}
          onSelectDate={view.selectDate}
          onOpenEmail={(id) => {
            setDaySheet(false);
            onOpenEmail(id);
          }}
          onAddEvent={() => {
            setDaySheet(false);
            setDialog({ mode: "new", date: view.selectedDate });
          }}
          onEditEvent={(event) => {
            setDaySheet(false);
            setDialog({ mode: "edit", event });
          }}
          className="border-0 p-0 shadow-none"
        />
      </BottomSheet>
      </>
      )}

      <button
        type="button"
        onClick={() => setDialog({ mode: "new", date: view.selectedDate })}
        aria-label="Add event"
        className="press fixed right-4 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-30 grid h-14 w-14 place-items-center rounded-full bg-accent text-white shadow-[0_8px_20px_rgba(0,61,124,0.35)] hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none sm:hidden"
      >
        <Plus className="h-6 w-6" aria-hidden="true" />
      </button>

      <FeedDialog open={feedOpen} onClose={() => setFeedOpen(false)} />
      <EventDialog
        target={dialog}
        onSave={onSaveEvent}
        onDelete={onDeleteEvent}
        onClose={() => setDialog(null)}
      />
    </main>
    </div>
  );
}
