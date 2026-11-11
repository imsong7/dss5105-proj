import { ArrowUpRight, Pencil } from "lucide-react";

import type { AcademicEvent, CalendarDeadline, PersonalEvent } from "../domain/calendar";
import { addDays, formatDayShort, formatTime, startOfWeek } from "../domain/calendar";
import { termWeek } from "../domain/academic";
import { courseStyle, titleWithoutCourse } from "../domain/course";
import { CourseToken } from "./CourseToken";

interface AgendaViewProps {
  deadlines: readonly CalendarDeadline[];
  academic: readonly AcademicEvent[];
  today: string;
  onOpenEmail: (id: string) => void;
  onEditEvent: (event: PersonalEvent) => void;
}

const DAYS_AHEAD = 60;

interface DayGroup {
  date: string;
  deadlines: CalendarDeadline[];
  academic: AcademicEvent[];
}

function groupByDay(
  deadlines: readonly CalendarDeadline[],
  academic: readonly AcademicEvent[],
  today: string,
): DayGroup[] {
  const last = addDays(today, DAYS_AHEAD);
  const groups = new Map<string, DayGroup>();

  function group(date: string): DayGroup {
    let found = groups.get(date);
    if (!found) {
      found = { date, deadlines: [], academic: [] };
      groups.set(date, found);
    }
    return found;
  }

  for (const item of deadlines) {
    if (item.date >= today && item.date <= last) {
      group(item.date).deadlines.push(item);
    }
  }

  for (const event of academic) {
    if (event.startDate >= today && event.startDate <= last) {
      group(event.startDate).academic.push(event);
    }
  }

  return [...groups.values()].sort((a, b) => a.date.localeCompare(b.date));
}

interface WeekGroup {
  start: string;
  days: DayGroup[];
}

/** Monday-first weeks, each holding its days in order. */
function groupByWeek(days: DayGroup[]): WeekGroup[] {
  const weeks: WeekGroup[] = [];
  for (const day of days) {
    const start = startOfWeek(day.date);
    const last = weeks[weeks.length - 1];
    if (last && last.start === start) {
      last.days.push(day);
    } else {
      weeks.push({ start, days: [day] });
    }
  }
  return weeks;
}

/** "Mon, 24 Nov" -> ["Mon", "24 Nov"]. */
function splitDay(date: string): [string, string] {
  const [weekday, rest] = formatDayShort(date).split(/,\s*/);
  return [weekday, rest ?? ""];
}

export function AgendaView({
  deadlines,
  academic,
  today,
  onOpenEmail,
  onEditEvent,
}: AgendaViewProps) {
  const days = groupByDay(deadlines, academic, today);

  if (days.length === 0) {
    return (
      <section
        aria-label="Agenda"
        className="rounded-2xl border border-line bg-surface px-6 py-12 text-center"
      >
        <p className="text-[15px] font-semibold text-ink">Nothing coming up</p>
        <p className="mx-auto mt-1.5 max-w-[40ch] text-[14px] text-muted">
          No dates in the next {DAYS_AHEAD} days. Add your own event, or load more mail.
        </p>
      </section>
    );
  }

  const thisWeek = startOfWeek(today);
  const weeks = groupByWeek(days);

  return (
    <section aria-label="Agenda" className="flex flex-col gap-4">
      {weeks.map((week) => {
        const end = addDays(week.start, 6);
        const title =
          week.start === thisWeek
            ? "This week"
            : week.start === addDays(thisWeek, 7)
              ? "Next week"
              : `Week of ${splitDay(week.start)[1]}`;
        const term = termWeek(academic, week.start);
        const count = week.days.reduce((sum, day) => sum + day.deadlines.length, 0);

        return (
          <div key={week.start} className="rounded-2xl border border-line bg-surface">
            <h2 className="flex flex-wrap items-baseline gap-x-2 border-b border-line px-4 py-3">
              <span className="text-[15px] font-semibold text-ink">{title}</span>
              <span className="text-[12px] text-muted tabular-nums">
                {term ? `Week ${term.week} · ` : ""}
                {splitDay(week.start)[1]} – {splitDay(end)[1]}
              </span>
              {count > 0 ? (
                <span className="ml-auto text-[12px] font-medium text-muted tabular-nums">
                  {count} {count === 1 ? "item" : "items"}
                </span>
              ) : null}
            </h2>

            <ol>
              {week.days.map((day) => {
                const [weekday, date] = splitDay(day.date);
                const isToday = day.date === today;

                return (
                  <li
                    key={day.date}
                    className="flex gap-3 border-t border-line/60 px-2 py-2 first:border-t-0"
                  >
                    <div className="w-[52px] shrink-0 px-2 pt-1.5">
                      <p className={`text-[12px] font-semibold ${isToday ? "text-accent" : "text-ink"}`}>
                        {isToday ? "Today" : weekday}
                      </p>
                      <p className="text-[11px] text-muted tabular-nums">{date}</p>
                    </div>

                    <ul className="min-w-0 flex-1">
                      {day.deadlines.map((item) => (
                        <li key={item.id}>
                          <button
                            type="button"
                            onClick={() =>
                              item.personal ? onEditEvent(item.personal) : onOpenEmail(item.emailId)
                            }
                            style={courseStyle(item.hue)}
                            className="group flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2 text-left transition-colors hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                          >
                            <span
                              aria-hidden="true"
                              className={`h-2 w-2 shrink-0 rounded-full ${
                                item.hue !== undefined
                                  ? "bg-[var(--course-border)]"
                                  : item.personal
                                    ? "bg-accent"
                                    : "bg-highlight"
                              }`}
                            />
                            <span className="min-w-0 flex-1 truncate text-[14px] text-ink">
                              {item.course ? titleWithoutCourse(item.subject) : item.subject}
                            </span>
                            {item.course ? (
                              <span className="shrink-0 max-sm:hidden">
                                <CourseToken code={item.course} hue={item.hue} />
                              </span>
                            ) : item.personal ? (
                              <span className="shrink-0 text-[12px] text-muted max-sm:hidden">Your event</span>
                            ) : null}
                            <span className="w-[58px] shrink-0 text-right text-[12px] text-muted tabular-nums">
                              {formatTime(item.time)}
                            </span>
                            {item.personal ? (
                              <Pencil className="h-3.5 w-3.5 shrink-0 text-muted" aria-label="Edit event" />
                            ) : (
                              <ArrowUpRight
                                className="h-3.5 w-3.5 shrink-0 text-muted opacity-0 transition-opacity group-hover:opacity-100"
                                aria-hidden="true"
                              />
                            )}
                          </button>
                        </li>
                      ))}

                      {day.academic.map((event) => (
                        <li
                          key={`${event.event}-${event.startDate}`}
                          className="flex min-h-9 items-center px-2 text-[13px] text-muted"
                        >
                          NUS · {event.event}
                          {event.endDate !== event.startDate ? ` (until ${event.endDate})` : ""}
                        </li>
                      ))}
                    </ul>
                  </li>
                );
              })}
            </ol>
          </div>
        );
      })}
    </section>
  );
}
