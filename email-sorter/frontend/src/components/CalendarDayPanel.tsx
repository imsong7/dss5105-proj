import { ArrowUpRight, Clock, Pencil, Plus } from "lucide-react";

import type {
  AcademicEvent,
  CalendarDeadline,
  PersonalEvent,
} from "../domain/calendar";
import {
  formatDayLong,
  formatDayPanel,
  formatDayShort,
  formatItemCount,
  formatTime,
} from "../domain/calendar";
import { courseStyle, titleWithoutCourse } from "../domain/course";
import { CourseToken } from "./CourseToken";

interface CalendarDayPanelProps {
  selectedDate: string;
  selectedDeadlines: readonly CalendarDeadline[];
  upcoming: readonly CalendarDeadline[];
  academic?: readonly AcademicEvent[];
  upcomingAcademic?: readonly AcademicEvent[];
  onSelectDate: (date: string) => void;
  onOpenEmail: (id: string) => void;
  onAddEvent: () => void;
  onEditEvent: (event: PersonalEvent) => void;
  className?: string;
}

export function CalendarDayPanel({
  selectedDate,
  selectedDeadlines,
  upcoming,
  onSelectDate,
  onOpenEmail,
  onAddEvent,
  onEditEvent,
  className = "",
}: CalendarDayPanelProps) {
  const itemCount = selectedDeadlines.length;
  const dayCountLabel =
    itemCount === 0 ? "Nothing on this day" : `${formatItemCount(itemCount)} on this day`;

  return (
    <aside
      aria-label="Items for the selected day"
      className={`flex min-w-0 flex-col gap-3 rounded-2xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${className}`}
    >
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {formatDayLong(selectedDate)} — {dayCountLabel}
      </p>

      <div className="flex items-center justify-between gap-2">
        <h2
          data-role="selected-day"
          className="text-[17px] leading-snug font-semibold tracking-[-0.01em] text-ink"
        >
          {formatDayPanel(selectedDate)}
        </h2>
        <button
          type="button"
          onClick={onAddEvent}
          aria-label="Add event on this day"
          title="Add event on this day"
          className="grid h-9 w-9 shrink-0 place-items-center rounded-xl text-accent hover:bg-accent-soft focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {itemCount === 0 ? (
        <p data-role="selected-count" className="-mt-2 text-[13px] text-muted">
          {dayCountLabel}
        </p>
      ) : null}

      {selectedDeadlines.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {selectedDeadlines.map((deadline) => (
            <li key={deadline.id}>
              <button
                type="button"
                data-role="calendar-event"
                data-email-id={deadline.emailId}
                onClick={() =>
                  deadline.personal
                    ? onEditEvent(deadline.personal)
                    : onOpenEmail(deadline.emailId)
                }
                style={courseStyle(deadline.hue)}
                className="group flex w-full flex-col gap-1.5 rounded-xl border border-line bg-surface p-3.5 text-left transition-colors hover:border-accent/30 hover:bg-surface-muted/50 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface focus-visible:outline-none"
              >
                <span className="flex flex-wrap items-center gap-1.5">
                  {deadline.course ? (
                    <CourseToken code={deadline.course} hue={deadline.hue} />
                  ) : null}
                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold tracking-[0.03em] text-highlight-dark">
                    <Clock className="h-3 w-3" aria-hidden="true" />
                    {formatTime(deadline.time)}
                  </span>
                  {deadline.personal ? (
                    <Pencil
                      className="ml-auto h-3.5 w-3.5 shrink-0 text-muted transition-colors group-hover:text-accent"
                      aria-label="Edit event"
                    />
                  ) : (
                    <ArrowUpRight
                      className="ml-auto h-3.5 w-3.5 shrink-0 text-muted transition-colors group-hover:text-accent"
                      aria-hidden="true"
                    />
                  )}
                </span>
                <span className="line-clamp-2 text-[14px] leading-5 font-semibold text-ink">
                  {deadline.course ? titleWithoutCourse(deadline.subject) : deadline.subject}
                </span>
                {deadline.personal ? (
                  deadline.personal.notes ? (
                    <span className="line-clamp-3 text-[12px] text-muted">
                      {deadline.personal.notes}
                    </span>
                  ) : null
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-1 border-t border-line pt-3">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-[13px] font-semibold text-ink">Coming up</p>
        </div>

        {upcoming.length > 0 ? (
          <ul className="mt-1 flex flex-col gap-0.5">
            {upcoming.map((deadline, index) => {
              // Same day as the row above: the date is already shown there.
              const sameDay = index > 0 && upcoming[index - 1].date === deadline.date;
              return (
              <li key={deadline.id} className={index > 0 && !sameDay ? "mt-1.5 border-t border-line/60 pt-1.5" : ""}>
                <button
                  type="button"
                  data-role="upcoming-deadline"
                  data-date={deadline.date}
                  onClick={() => onSelectDate(deadline.date)}
                  className="flex min-h-11 w-full items-start gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface focus-visible:outline-none"
                >
                  <span className="w-[72px] shrink-0 whitespace-nowrap pt-0.5 text-[11px] font-medium tracking-[0.02em] text-highlight-dark">
                    {sameDay ? (
                      <span className="sr-only">{formatDayShort(deadline.date)}</span>
                    ) : (
                      formatDayShort(deadline.date)
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-ink">
                      {deadline.subject}
                    </span>
                    <span className="block truncate text-[12px] text-muted">
                      {formatTime(deadline.time)}
                    </span>
                  </span>
                </button>
              </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-1.5 text-[13px] text-muted">
            No further dates in your loaded mail.
          </p>
        )}
      </div>
    </aside>
  );
}
