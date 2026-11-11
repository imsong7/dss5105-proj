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

  // One connected strip that never wraps: equal segments, scrolling sideways if there are many.
  return (
    <ul
      aria-label="Your courses"
      className="flex gap-[3px] overflow-x-auto rounded-lg [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {tiles.map((tile) => {
        const soon = tile.next !== undefined && daysBetween(today, tile.next) <= 1;
        const nextText = tile.next ? `next ${shortWhen(tile.next, today)}` : "nothing due";

        return (
          <li key={tile.code} className="min-w-[64px] flex-1">
            <button
              type="button"
              onClick={() => openCourse?.(tile.code)}
              title={`${tile.code}: ${tile.thisWeek} due this week, ${nextText}`}
              aria-label={`Open course ${tile.code}: ${tile.thisWeek} due this week, ${nextText}`}
              style={courseStyle(tile.hue)}
              className="flex h-8 w-full items-center justify-center gap-1 rounded-[5px] bg-[var(--course-bg)] px-2 text-[11px] font-bold tracking-[0.02em] whitespace-nowrap text-[var(--course-text)] transition-[filter] hover:brightness-95 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              {tile.code}
              {tile.thisWeek > 0 ? (
                <span
                  className={`grid h-4 min-w-4 place-items-center rounded-full px-1 text-[10px] tabular-nums ${
                    soon ? "bg-surface text-highlight-dark" : "opacity-70"
                  }`}
                >
                  {tile.thisWeek}
                </span>
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
