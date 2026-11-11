import type { CalendarDeadline } from "../domain/calendar";
import { addDays, daysBetween, formatDayShort, startOfWeek } from "../domain/calendar";
import { courseStyle } from "../domain/course";
import { itemKey } from "../domain/today";
import { useOpenCourse } from "../contexts/CourseContext";

interface CourseChipsProps {
  courses: readonly { code: string; hue: number }[];
  deadlines: readonly CalendarDeadline[];
  isDone: (key: string) => boolean;
  today: string;
}

/** "Today", "Tmrw", "Thu", "24 Nov": as short as the date allows. */
function shortWhen(date: string, today: string): string {
  const diff = daysBetween(today, date);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tmrw";
  const [weekday, day] = formatDayShort(date).split(/,\s*/);
  return diff < 7 ? weekday : (day ?? weekday);
}

/**
 * One tile per course: the code, how much is due this week, and when the next
 * item is. Sorted so the course that needs you soonest comes first.
 */
export function CourseChips({ courses, deadlines, isDone, today }: CourseChipsProps) {
  const openCourse = useOpenCourse();

  if (courses.length === 0) {
    return null;
  }

  const weekEnd = addDays(startOfWeek(today), 6);
  const tiles = courses
    .map((course) => {
      const upcoming = deadlines
        .filter((item) => item.course === course.code && item.date >= today && !isDone(itemKey(item)))
        .sort((a, b) => a.date.localeCompare(b.date));
      return {
        ...course,
        next: upcoming[0]?.date,
        thisWeek: upcoming.filter((item) => item.date <= weekEnd).length,
      };
    })
    .sort((a, b) => (a.next ?? "9999").localeCompare(b.next ?? "9999"));

  return (
    <ul aria-label="Your courses" className="flex flex-wrap gap-1.5">
      {tiles.map((tile) => {
        const soon = tile.next !== undefined && daysBetween(today, tile.next) <= 1;
        const nextText = tile.next ? `next ${shortWhen(tile.next, today)}` : "nothing due";

        return (
          <li key={tile.code}>
            <button
              type="button"
              onClick={() => openCourse?.(tile.code)}
              title={`${tile.code}: ${tile.thisWeek} due this week, ${nextText}`}
              aria-label={`Open course ${tile.code}: ${tile.thisWeek} due this week, ${nextText}`}
              style={courseStyle(tile.hue)}
              className="press inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface pr-1.5 pl-2.5 text-[12px] font-bold tracking-[0.03em] text-ink transition-colors hover:border-[var(--course-border)] focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--course-accent)]" aria-hidden="true" />
              {tile.code}
              {tile.thisWeek > 0 ? (
                <span
                  className={`grid h-5 min-w-5 place-items-center rounded-md px-1 text-[11px] tabular-nums ${
                    soon ? "bg-highlight-soft text-highlight-dark" : "bg-surface-muted text-muted"
                  }`}
                >
                  {tile.thisWeek}
                </span>
              ) : (
                <span className="w-1" aria-hidden="true" />
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
