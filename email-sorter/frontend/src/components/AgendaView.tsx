import { ArrowUpRight, Pencil } from "lucide-react";

import type { AcademicEvent, CalendarDeadline, PersonalEvent } from "../domain/calendar";
import { addDays, formatDayLong, formatTime, relativeDay } from "../domain/calendar";
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
        className="rounded-xl border border-line bg-surface px-6 py-12 text-center"
      >
        <p className="text-[15px] font-semibold text-ink">Nothing coming up</p>
        <p className="mx-auto mt-1.5 max-w-[40ch] text-[14px] text-muted">
          No dates in the next {DAYS_AHEAD} days. Add your own event, or load more mail.
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Agenda" className="flex flex-col gap-3">
      {days.map((day) => {
        const when = relativeDay(day.date, today);

        return (
          <div
            key={day.date}
            className="rounded-xl border border-line bg-surface p-3 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
          >
            <h2 className="flex flex-wrap items-baseline gap-x-2 px-1 pb-1 text-[14px] font-semibold text-ink">
              {formatDayLong(day.date)}
              <span
                className={`text-[13px] font-medium ${
                  when.tone === "soon" ? "text-highlight-dark" : "text-muted"
                }`}
              >
                {when.text}
              </span>
            </h2>

            <ul className="flex flex-col gap-1.5">
              {day.deadlines.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() =>
                      item.personal ? onEditEvent(item.personal) : onOpenEmail(item.emailId)
                    }
                    style={courseStyle(item.hue)}
                    className={`flex min-h-11 w-full items-center gap-3 rounded-[10px] px-3 py-2 text-left transition-colors hover:brightness-95 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
                      item.hue !== undefined
                        ? "bg-[var(--course-bg)]"
                        : item.personal
                          ? "bg-accent-soft"
                          : "bg-highlight-soft"
                    }`}
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
                    <span className="w-[64px] shrink-0 text-[13px] font-medium text-ink/70">
                      {formatTime(item.time)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-medium text-ink">
                        {item.course ? titleWithoutCourse(item.subject) : item.subject}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-[13px] text-ink/70">
                        {item.course ? <CourseToken code={item.course} hue={item.hue} /> : null}
                        {item.personal ? "Your event" : item.label}
                      </span>
                    </span>
                    {item.personal ? (
                      <Pencil className="h-3.5 w-3.5 shrink-0 text-muted" aria-label="Edit event" />
                    ) : (
                      <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden="true" />
                    )}
                  </button>
                </li>
              ))}

              {day.academic.map((event) => (
                <li
                  key={`${event.event}-${event.startDate}`}
                  className="px-3 py-1 text-[13px] text-muted"
                >
                  NUS · {event.event}
                  {event.endDate !== event.startDate ? ` (until ${event.endDate})` : ""}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
