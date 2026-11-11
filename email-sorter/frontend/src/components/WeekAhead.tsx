import type { AcademicEvent, CalendarDeadline } from "../domain/calendar";
import { addDays, formatDayShort, formatTime, relativeDay, startOfWeek } from "../domain/calendar";
import { termWeek } from "../domain/academic";
import { courseStyle, titleWithoutCourse } from "../domain/course";
import { itemKey } from "../domain/today";
import { useOpenCourse } from "../contexts/CourseContext";

interface WeekAheadProps {
  deadlines: readonly CalendarDeadline[];
  isDone: (key: string) => boolean;
  academic: readonly AcademicEvent[];
  courses: readonly { code: string; hue: number }[];
  today: string;
  onOpenDate: (date: string) => void;
  onOpenEmail: (id: string) => void;
}

const PER_DAY = 3;
const LATER_WEEKS = 4;

/** "Mon, 10 Nov" -> { weekday: "Mon", day: "10 Nov" }. */
function splitDay(date: string) {
  const [weekday, day] = formatDayShort(date).split(/,\s*/);
  return { weekday, day: day ?? "" };
}

const titleOf = (item: CalendarDeadline) => (item.course ? titleWithoutCourse(item.subject) : item.subject);

/**
 * The Today side panel: this week day by day, a one-line look further ahead,
 * and what each course needs next. One colour means "due"; exams are named.
 */
export function WeekAhead({
  deadlines,
  isDone,
  academic,
  courses,
  today,
  onOpenDate,
  onOpenEmail,
}: WeekAheadProps) {
  const openCourse = useOpenCourse();
  const start = startOfWeek(today);
  const end = addDays(start, 6);
  const open = deadlines
    .filter((item) => !isDone(itemKey(item)))
    .sort((a, b) => a.date.localeCompare(b.date) || (a.time ?? "").localeCompare(b.time ?? ""));
  const term = termWeek(academic, start);
  const openItem = (item: CalendarDeadline) =>
    item.personal || !item.emailId ? onOpenDate(item.date) : onOpenEmail(item.emailId);

  const days = Array.from({ length: 7 }, (_, index) => {
    const date = addDays(start, index);
    return { date, items: open.filter((item) => item.date === date) };
  }).filter((day) => day.date >= today || day.items.length > 0);
  const thisWeek = days.reduce((sum, day) => sum + day.items.length, 0);

  const later = Array.from({ length: LATER_WEEKS }, (_, index) => {
    const weekStart = addDays(start, (index + 1) * 7);
    const weekEnd = addDays(weekStart, 6);
    return {
      start: weekStart,
      label: index === 0 ? "Next wk" : splitDay(weekStart).day,
      count: open.filter((item) => item.date >= weekStart && item.date <= weekEnd).length,
    };
  });
  const busiest = Math.max(...later.map((week) => week.count));

  const courseRows = courses
    .map((course) => {
      const upcoming = open.filter((item) => item.course === course.code && item.date >= today);
      return {
        ...course,
        next: upcoming[0],
        thisWeek: upcoming.filter((item) => item.date <= end).length,
      };
    })
    .sort((a, b) => (a.next?.date ?? "9999").localeCompare(b.next?.date ?? "9999"));

  if (open.length === 0 && courses.length === 0) {
    return null;
  }

  return (
    <section aria-label="Week ahead" className="rounded-xl border border-line bg-surface">
      <header className="flex items-baseline justify-between gap-3 px-4 pt-3.5 pb-2">
        <h2 className="text-[15px] font-semibold text-ink">This week</h2>
        <p className="text-[12px] text-muted tabular-nums">
          {term ? `Week ${term.week} · ` : ""}
          {splitDay(start).day} – {splitDay(end).day}
        </p>
      </header>

      {thisWeek === 0 ? (
        <p className="px-4 pb-3 text-[14px] text-muted">Nothing due this week.</p>
      ) : (
        <ol className="px-2 pb-2">
          {days.map(({ date, items }) => {
            const isToday = date === today;
            const past = date < today;
            const { weekday, day } = splitDay(date);

            return (
              <li key={date} className="flex gap-2 border-t border-line/70 py-1.5 first:border-t-0">
                <button
                  type="button"
                  onClick={() => onOpenDate(date)}
                  aria-label={`Open ${formatDayShort(date)} in the calendar`}
                  className="flex min-h-9 w-[56px] shrink-0 flex-col items-start justify-center rounded-md px-2 text-left hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                >
                  <span className={`text-[12px] font-semibold ${isToday ? "text-accent" : past ? "text-action-now-fg" : "text-ink"}`}>
                    {isToday ? "Today" : weekday}
                  </span>
                  <span className="text-[11px] text-muted tabular-nums">{day.replace(/\s\w+$/, "")}</span>
                </button>

                {items.length === 0 ? (
                  <span className="flex min-h-9 items-center text-[13px] text-muted/70">Free</span>
                ) : (
                  <ul className="min-w-0 flex-1">
                    {items.slice(0, PER_DAY).map((item) => (
                      <li key={item.id}>
                        <button
                          type="button"
                          onClick={() => openItem(item)}
                          className="flex min-h-9 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                        >
                          {item.course ? (
                            <span
                              style={courseStyle(item.hue)}
                              className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--course-accent)]"
                              aria-hidden="true"
                            />
                          ) : null}
                          <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                            {item.label === "Exam" && !item.personal ? (
                              <span className="mr-1.5 font-semibold text-action-now-fg">Exam</span>
                            ) : null}
                            {titleOf(item)}
                          </span>
                          <span className="shrink-0 text-[11px] text-muted tabular-nums">
                            {past ? "Overdue" : formatTime(item.time)}
                          </span>
                        </button>
                      </li>
                    ))}
                    {items.length > PER_DAY ? (
                      <li>
                        <button
                          type="button"
                          onClick={() => onOpenDate(date)}
                          className="min-h-8 rounded-md px-2 text-[12px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                        >
                          +{items.length - PER_DAY} more
                        </button>
                      </li>
                    ) : null}
                  </ul>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {later.some((week) => week.count > 0) ? (
        <div className="flex flex-wrap items-center gap-x-1 gap-y-1 border-t border-line px-4 py-2.5 text-[12px]">
          <span className="mr-1 text-muted">Later</span>
          {later.map((week) => (
            <button
              key={week.start}
              type="button"
              onClick={() => onOpenDate(week.start)}
              aria-label={`Week of ${formatDayShort(week.start)}: ${week.count} due`}
              className="inline-flex min-h-8 items-baseline gap-1 rounded-md px-1.5 hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              <span className="text-muted">{week.label}</span>
              <span
                className={`tabular-nums ${
                  week.count > 0 && week.count === busiest ? "font-bold text-ink" : "font-medium text-ink/70"
                }`}
              >
                {week.count}
              </span>
            </button>
          ))}
        </div>
      ) : null}

      {courseRows.length > 0 ? (
        <div className="border-t border-line px-2 pt-2.5 pb-2">
          <h3 className="px-2 pb-1 text-[12px] font-semibold text-muted">Courses</h3>
          <ul>
            {courseRows.map((course) => {
              const when = course.next ? relativeDay(course.next.date, today).text : "";

              return (
                <li key={course.code}>
                  <button
                    type="button"
                    onClick={() => openCourse?.(course.code)}
                    aria-label={`Open course ${course.code}`}
                    style={courseStyle(course.hue)}
                    className="flex min-h-11 w-full items-center gap-2.5 rounded-md px-2 text-left hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                  >
                    <span className="h-2 w-2 shrink-0 rounded-full bg-[var(--course-accent)]" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-semibold tracking-[0.02em] text-ink">{course.code}</span>
                      <span className="block truncate text-[12px] text-muted">
                        {course.next ? `${titleOf(course.next)} · ${when}` : "Nothing due"}
                      </span>
                    </span>
                    {course.thisWeek > 0 ? (
                      <span className="shrink-0 text-[12px] font-medium text-ink tabular-nums">
                        {course.thisWeek} this wk
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
