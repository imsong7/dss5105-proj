import { markerLabel, markerSpoken } from "../domain/academic";
import type { AcademicMarker } from "../domain/academic";
import { courseStyle, titleWithoutCourse } from "../domain/course";
import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";

import type {
  CalendarDeadline,
  MonthCell,
} from "../domain/calendar";
import {
  addDays,
  formatDayLong,
  formatItemCount,
  formatTime,
  monthTitle,
  WEEKDAY_LABELS,
} from "../domain/calendar";

interface CalendarMonthProps {
  month: string;
  cells: readonly MonthCell[];
  deadlinesByDate: ReadonlyMap<string, CalendarDeadline[]>;
  academicMarkers: (date: string) => AcademicMarker[];
  selectedDate: string;
  todayKey: string;
  monthCount: number;
  onSelectDate: (date: string) => void;
  onAddOnDate: (date: string) => void;
  onPrevMonth: () => void;
  onNextMonth: () => void;
  onToday: () => void;
}

const CONTROL =
  "inline-flex h-11 items-center justify-center rounded-[10px] border border-line bg-surface text-[13px] font-medium text-ink transition-colors hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface focus-visible:outline-none";

export function CalendarMonth({
  month,
  cells,
  deadlinesByDate,
  academicMarkers,
  selectedDate,
  todayKey,
  monthCount,
  onSelectDate,
  onAddOnDate,
  onPrevMonth,
  onNextMonth,
  onToday,
}: CalendarMonthProps) {
  const gridRef = useRef<HTMLDivElement>(null);
  const focusAfterRender = useRef<string | null>(null);

  useEffect(() => {
    const target = focusAfterRender.current;

    if (!target) {
      return;
    }

    const node = gridRef.current?.querySelector<HTMLButtonElement>(
      `[data-date="${target}"]`,
    );

    if (node) {
      focusAfterRender.current = null;
      node.focus();
    }
  }, [selectedDate, month]);

  function handleDayKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    date: string,
  ) {
    let delta: number;

    switch (event.key) {
      case "ArrowLeft":
        delta = -1;
        break;
      case "ArrowRight":
        delta = 1;
        break;
      case "ArrowUp":
        delta = -7;
        break;
      case "ArrowDown":
        delta = 7;
        break;
      default:
        return;
    }

    event.preventDefault();
    const target = addDays(date, delta);
    focusAfterRender.current = target;
    onSelectDate(target);
  }

  return (
    <section
      aria-label="Month calendar"
      className="flex min-w-0 flex-col rounded-xl border border-line bg-surface p-3 shadow-[0_1px_2px_rgba(0,0,0,0.04)] sm:p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-[12px] font-medium tracking-[0.04em] text-muted max-sm:hidden">
            <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
            Calendar
          </p>
          <h2
            data-role="month-title"
            className="mt-0.5 text-[21px] font-semibold tracking-[-0.01em] text-ink sm:text-[21px]"
            aria-live="polite"
          >
            {monthTitle(month)}
          </h2>
        </div>

        <div className="flex items-center gap-1.5">
          <button type="button" onClick={onToday} className={`${CONTROL} px-2.5`}>
            Today
          </button>
          <button
            type="button"
            onClick={onPrevMonth}
            aria-label="Previous month"
            className={`${CONTROL} w-11`}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={onNextMonth}
            aria-label="Next month"
            className={`${CONTROL} w-11`}
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      <p data-role="month-summary" className="mt-1 text-[13px] text-muted max-sm:hidden">
        {monthCount} date{monthCount === 1 ? "" : "s"} this month
      </p>

      <div className="mt-4 grid grid-cols-7 gap-1" aria-hidden="true">
        {WEEKDAY_LABELS.map((label) => (
          <span
            key={label}
            className="py-1 text-center text-[11px] font-medium tracking-[0.04em] text-muted uppercase"
          >
            {label}
          </span>
        ))}
      </div>

      <div
        ref={gridRef}
        role="group"
        aria-label={`${monthTitle(month)} days`}
        className="mt-1 grid grid-cols-7 gap-1"
      >
        {cells.map((cell) => {
          const deadlines = deadlinesByDate.get(cell.date) ?? [];
          const markers = academicMarkers(cell.date);
          const shownDeadlines = deadlines.slice(0, 2);
          const hidden = deadlines.length - shownDeadlines.length;
          const isSelected = cell.date === selectedDate;
          const isToday = cell.date === todayKey;

          return (
            <button
              key={cell.date}
              type="button"
              data-role="day"
              data-date={cell.date}
              tabIndex={isSelected ? 0 : -1}
              aria-pressed={isSelected}
              aria-label={`${formatDayLong(cell.date)}${
                isToday ? ", today" : ""
              }, ${formatItemCount(deadlines.length)}${
                markers.length
                  ? `, ${markers.map(markerSpoken).join(", ")}`
                  : ""
              }`}
              onClick={() => onSelectDate(cell.date)}
              onDoubleClick={() => onAddOnDate(cell.date)}
              title="Double-click to add an event"
              onKeyDown={(event) => handleDayKeyDown(event, cell.date)}
              className={`relative flex min-h-[58px] flex-col gap-1 rounded-[8px] p-1.5 text-left transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface focus-visible:outline-none lg:min-h-[78px] ${
                !cell.inMonth
                  ? "bg-transparent hover:bg-surface-muted/60"
                  : isSelected
                    ? "bg-accent-soft ring-1 ring-accent/25"
                    : cell.isWeekend
                      ? "bg-surface-muted/45 hover:bg-surface-muted"
                      : "bg-transparent hover:bg-surface-muted/60"
              }`}
            >
              <span className="flex items-center gap-1">
                <span
                  className={`grid h-6 w-6 place-items-center rounded-full text-[12px] font-semibold tabular-nums ${
                    isToday
                      ? "bg-highlight text-ink"
                      : cell.inMonth
                        ? "text-ink"
                        : "text-muted"
                  }`}
                >
                  {cell.day}
                </span>
                {deadlines.length > 0 ? (
                  <span
                    className={`ml-auto text-[11px] font-semibold tabular-nums lg:hidden ${
                      isSelected ? "text-accent-dark" : "text-muted"
                    }`}
                    aria-hidden="true"
                  >
                    {deadlines.length}
                  </span>
                ) : null}
              </span>

              {deadlines.length > 0 ? (
                <span className="hidden min-w-0 flex-col gap-1 lg:flex">
                  {shownDeadlines.map((deadline) => (
                    <span
                      key={deadline.id}
                      title={deadline.subject}
                      style={courseStyle(deadline.hue)}
                      className={`min-w-0 rounded-[5px] px-1.5 py-1 ${
                        deadline.hue !== undefined
                          ? "bg-[var(--course-bg)]"
                          : deadline.personal
                            ? "bg-accent-soft"
                            : "bg-highlight-soft"
                      }`}
                    >
                      <span
                        className={`block truncate text-[11px] leading-[14px] font-semibold ${
                          deadline.hue !== undefined
                            ? "text-[var(--course-text)]"
                            : "text-ink"
                        }`}
                      >
                        {deadline.course
                          ? titleWithoutCourse(deadline.subject)
                          : deadline.subject}
                      </span>
                      <span
                        className={`block truncate text-[11px] leading-[13px] ${
                          deadline.hue !== undefined
                            ? "text-[var(--course-text)]/80"
                            : deadline.personal
                              ? "text-accent-dark"
                              : "text-highlight-dark"
                        }`}
                      >
                        {deadline.course ?? deadline.label} ·{" "}
                        {formatTime(deadline.time)}
                      </span>
                    </span>
                  ))}
                  {hidden > 0 ? (
                    <span className="px-1.5 text-[11px] text-muted">
                      +{hidden} more
                    </span>
                  ) : null}
                </span>
              ) : null}

              {markers.length > 0 ? (
                <span
                  title={markers.map(markerSpoken).join(" · ")}
                  className="mt-auto hidden min-w-0 truncate px-0.5 text-center text-[11px] leading-[13px] text-muted lg:block"
                >
                  {markerLabel(markers[0])}
                  {markers.length > 1 ? ` +${markers.length - 1}` : ""}
                </span>
              ) : null}

              {deadlines.length > 0 || markers.length > 0 ? (
                <span
                  className="flex gap-0.5 pt-0.5 lg:hidden"
                  aria-hidden="true"
                >
                  {markers.length > 0 ? (
                    <span className="h-1.5 w-1.5 rounded-[2px] bg-muted/60" />
                  ) : null}
                  {deadlines.slice(0, 3).map((deadline) => (
                    <span
                      key={deadline.id}
                      style={courseStyle(deadline.hue)}
                      className={`h-1.5 w-1.5 rounded-full ${
                        deadline.hue !== undefined
                          ? "bg-[var(--course-accent)]"
                          : isSelected
                            ? "bg-accent"
                            : "bg-highlight"
                      }`}
                    />
                  ))}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}
