import { useState } from "react";

import type { CalendarDeadline } from "../domain/calendar";
import { addDays, formatDayShort, formatTime, startOfWeek } from "../domain/calendar";
import type { AcademicEvent } from "../domain/calendar";
import { titleWithoutCourse } from "../domain/course";
import { CourseToken } from "./CourseToken";
import { itemKey } from "../domain/today";
import { termWeek } from "../domain/academic";

interface WorkloadStripProps {
  /** Every dated item, done ones included: they show as the finished part of a bar. */
  deadlines: readonly CalendarDeadline[];
  isDone: (key: string) => boolean;
  academic: readonly AcademicEvent[];
  today: string;
  onOpenDate: (date: string) => void;
  onOpenEmail: (id: string) => void;
}

const WEEKS = 6;
const CROWDED = 3;
const MAX_BAR = 44;

interface Week {
  start: string;
  end: string;
  label: string;
  termLabel: string;
  items: CalendarDeadline[];
  todo: number;
  done: number;
  exams: number;
}

const RANGE = (start: string, end: string) =>
  `${formatDayShort(start).replace(/^\w+,\s*/, "")} – ${formatDayShort(end).replace(/^\w+,\s*/, "")}`;

export function WorkloadStrip({
  deadlines,
  isDone,
  academic,
  today,
  onOpenDate,
  onOpenEmail,
}: WorkloadStripProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const first = startOfWeek(today);

  const weeks: Week[] = Array.from({ length: WEEKS }, (_, index) => {
    const start = addDays(first, index * 7);
    const end = addDays(start, 6);
    const term = termWeek(academic, start);
    const short = formatDayShort(start).replace(/^\w+,\s*/, "");
    const items = deadlines.filter((item) => item.date >= start && item.date <= end);
    const finished = items.filter((item) => isDone(itemKey(item)));
    const open = items.filter((item) => !isDone(itemKey(item)));

    return {
      start,
      end,
      // Plain words for the next two weeks, a date after that. The term week
      // number moves to the detail heading.
      label: index === 0 ? "This wk" : index === 1 ? "Next wk" : short,
      termLabel: term ? `Wk ${term.week}` : "",
      items,
      todo: open.length,
      done: finished.length,
      exams: open.filter((item) => item.label === "Exam" && !item.personal).length,
    };
  });

  const total = weeks.reduce((sum, week) => sum + week.todo + week.done, 0);
  if (total === 0) {
    return null;
  }

  const toDo = weeks.reduce((sum, week) => sum + week.todo, 0);
  const busiest = Math.max(...weeks.map((week) => week.todo + week.done));
  const peak = Math.max(...weeks.map((week) => week.todo));
  const chosen = weeks.find((week) => week.start === selected) ?? null;
  const hasExam = weeks.some((week) => week.exams > 0);
  const hasDone = weeks.some((week) => week.done > 0);

  const busiestIndex = weeks.findIndex((week) => week.todo === peak);
  const summary =
    toDo === 0
      ? "Everything here is done."
      : peak <= 1
        ? "A light stretch: at most one thing due each week."
        : busiestIndex === 0
          ? `This week is the busiest, with ${peak} to do.`
          : `Busiest: ${busiestIndex === 1 ? "next week" : `week of ${weeks[busiestIndex].label}`}, with ${peak} to do.`;

  // Days with several things due, in the next two weeks.
  const perDay = new Map<string, number>();
  for (const item of deadlines) {
    if (item.date >= today && item.date <= addDays(today, 13) && !isDone(itemKey(item))) {
      perDay.set(item.date, (perDay.get(item.date) ?? 0) + 1);
    }
  }
  const crowded = [...perDay.entries()]
    .filter(([, count]) => count >= CROWDED)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(0, 2);

  return (
    <section
      aria-label="Workload for the next six weeks"
      className="rounded-2xl border border-line bg-surface px-4 py-3.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
    >
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <p className="text-[12px] font-medium text-muted">Due per week</p>
        <p
          className={`rounded-full px-2.5 py-0.5 text-[12px] font-semibold tabular-nums ${
            toDo === 0 ? "bg-accent-soft text-accent" : "bg-highlight-soft text-highlight-dark"
          }`}
        >
          {toDo === 0 ? "All done" : `${toDo} to do`}
        </p>
      </div>
      <ul className="flex items-end justify-between gap-1.5">
        {weeks.map((week, index) => {
          const all = week.todo + week.done;
          const height = all ? Math.max(8, Math.round((all / busiest) * MAX_BAR)) : 3;
          const share = (part: number) => (all ? (part / all) * 100 : 0);
          const isPeak = week.todo > 0 && week.todo === peak;
          const active = week.start === selected;

          return (
            <li key={week.start} className="min-w-0 flex-1">
              <button
                type="button"
                aria-pressed={active}
                disabled={all === 0}
                onClick={() => setSelected(active ? null : week.start)}
                title={`${week.label}: ${week.todo} to do${week.done ? `, ${week.done} done` : ""}`}
                aria-label={`${index === 0 ? "This week" : index === 1 ? "Next week" : `Week of ${week.label}`}, ${week.todo} to do${week.done ? `, ${week.done} done` : ""}`}
                className={`flex min-h-11 w-full flex-col items-center justify-end gap-1 rounded-lg px-0.5 pt-1 transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none enabled:hover:bg-surface-muted ${
                  active ? "bg-accent-soft" : ""
                }`}
              >
                <span className="text-[12px] font-semibold text-ink tabular-nums">
                  {week.todo || ""}
                </span>
                {all === 0 ? (
                  <span style={{ height }} className="w-full max-w-[34px] rounded-[5px] bg-line" />
                ) : (
                  <span
                    style={{ height, animationDelay: `${index * 70}ms` }}
                    className={`bar-grow flex w-full max-w-[34px] flex-col-reverse overflow-hidden rounded-[7px] ${
                      index === 0 ? "ring-2 ring-accent/30" : ""
                    }`}
                  >
                    {week.done > 0 ? (
                      <span style={{ height: `${share(week.done)}%` }} className="bg-line" />
                    ) : null}
                    {week.exams > 0 ? (
                      <span style={{ height: `${share(week.exams)}%` }} className="bg-action-now-fg" />
                    ) : null}
                    {week.todo - week.exams > 0 ? (
                      <span
                        style={{ height: `${share(week.todo - week.exams)}%` }}
                        className={isPeak ? "bg-gradient-to-t from-highlight to-[#f7a24b]" : "bg-gradient-to-t from-accent/80 to-accent/55"}
                      />
                    ) : null}
                  </span>
                )}
                <span className="whitespace-nowrap text-[11px] text-muted">{week.label}</span>
              </button>
            </li>
          );
        })}
      </ul>

      <DayStrip
        start={weeks[0].start}
        deadlines={deadlines}
        isDone={isDone}
        today={today}
        onOpenDate={onOpenDate}
      />

      <p className="mt-2 text-[13px] text-ink">{summary}</p>
      <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-accent/70" aria-hidden="true" />
          Due
        </span>
        {hasExam ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-action-now-fg" aria-hidden="true" />
            Exam
          </span>
        ) : null}
        {hasDone ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-line" aria-hidden="true" />
            Done
          </span>
        ) : null}
        <span className="ml-auto">Tap a bar to see what is due</span>
      </p>

      {chosen ? (
        <div className="mt-3 border-t border-line pt-3">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-[14px] font-semibold text-ink">
              {chosen.termLabel ? `${chosen.termLabel} · ` : ""}{RANGE(chosen.start, chosen.end)}
            </h3>
            <button
              type="button"
              onClick={() => onOpenDate(chosen.start)}
              className="min-h-11 shrink-0 rounded-lg px-1 text-[13px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              Open in calendar
            </button>
          </div>
          <ul className="-mt-1 flex flex-col">
            {[...chosen.items]
              .sort((a, b) => a.date.localeCompare(b.date) || (a.time ?? "").localeCompare(b.time ?? ""))
              .map((item) => {
                const finished = isDone(itemKey(item));
                const title = item.course ? titleWithoutCourse(item.subject) : item.subject;

                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => (item.personal || !item.emailId ? onOpenDate(item.date) : onOpenEmail(item.emailId))}
                      className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-1 text-left hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
                        finished ? "opacity-55" : ""
                      }`}
                    >
                      <span className="w-[74px] shrink-0 text-[12px] font-semibold text-highlight-dark">
                        {formatDayShort(item.date).split(",")[0]} {Number(item.date.slice(8))}
                      </span>
                      <span className={`min-w-0 flex-1 truncate text-[14px] text-ink ${finished ? "line-through" : ""}`}>
                        {title}
                      </span>
                      {item.course ? (
                        <span className="max-sm:hidden">
                          <CourseToken code={item.course} hue={item.hue} />
                        </span>
                      ) : null}
                      <span className="shrink-0 text-[12px] text-muted">{formatTime(item.time)}</span>
                    </button>
                  </li>
                );
              })}
          </ul>
        </div>
      ) : null}

      {crowded.length > 0 ? (
        <p className="mt-2 rounded-lg bg-highlight-soft px-3 py-2 text-[13px] font-medium text-highlight-dark">
          Heads up: {crowded
            .map(([date, count]) => `${count} things due ${formatDayShort(date)}`)
            .join(" · ")}
        </p>
      ) : null}
    </section>
  );
}

const LETTERS = ["M", "T", "W", "T", "F", "S", "S"];

/** The seven days of this week: how many things are due on each, today ringed. */
function DayStrip({
  start,
  deadlines,
  isDone,
  today,
  onOpenDate,
}: {
  start: string;
  deadlines: readonly CalendarDeadline[];
  isDone: (key: string) => boolean;
  today: string;
  onOpenDate: (date: string) => void;
}) {
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = addDays(start, index);
    const open = deadlines.filter((item) => item.date === date && !isDone(itemKey(item))).length;
    return { date, open, letter: LETTERS[index], number: Number(date.slice(8)) };
  });

  if (days.every((day) => day.open === 0)) {
    return null;
  }

  return (
    <ul aria-label="This week by day" className="mt-3 grid grid-cols-7 gap-1">
      {days.map((day) => {
        const isToday = day.date === today;
        const past = day.date < today;

        return (
          <li key={day.date}>
            <button
              type="button"
              onClick={() => onOpenDate(day.date)}
              aria-label={`${formatDayShort(day.date)}, ${day.open} to do`}
              className={`flex min-h-12 w-full flex-col items-center justify-center gap-0.5 rounded-lg transition-colors hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
                past ? "opacity-50" : ""
              }`}
            >
              <span className="text-[11px] font-medium text-muted">{day.letter}</span>
              <span
                className={`grid h-7 w-7 place-items-center rounded-full text-[12px] font-semibold tabular-nums ${
                  day.open >= 3
                    ? "bg-highlight text-black"
                    : day.open > 0
                      ? "bg-accent-soft text-accent"
                      : "text-muted"
                } ${isToday ? "ring-2 ring-accent" : ""}`}
              >
                {day.number}
              </span>
              <span className="flex h-1 gap-0.5" aria-hidden="true">
                {Array.from({ length: Math.min(day.open, 3) }, (_, dot) => (
                  <span key={dot} className={`h-1 w-1 rounded-full ${day.open >= 3 ? "bg-highlight" : "bg-accent"}`} />
                ))}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
