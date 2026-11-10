import { useState } from "react";
import { ArrowLeft } from "lucide-react";

import { formatDayShort, formatTime, relativeDay } from "../domain/calendar";
import { courseCode, isCanvasEmail, titleWithoutCourse } from "../domain/course";
import type { InboxEmail } from "../domain/email";
import { formatListDate } from "../lib/format";
import type { CalendarView } from "../hooks/useCalendarView";
import { CourseToken } from "./CourseToken";

interface CoursePageProps {
  code: string;
  calendar: CalendarView;
  emails: readonly InboxEmail[];
  onBack: () => void;
  onOpenEmail: (id: string) => void;
}

const LIMIT = 6;

const ROW =
  "flex min-h-11 w-full items-start gap-3 rounded-[10px] px-3 py-2 text-left hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none";

function Block({
  title,
  rows,
}: {
  title: string;
  rows: React.ReactNode[];
}) {
  const [all, setAll] = useState(false);

  if (rows.length === 0) {
    return null;
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-2 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <h2 className="flex items-baseline gap-2 px-3 pt-2 pb-1 text-[14px] font-semibold text-ink">
        {title}
        <span className="text-[12px] font-medium text-muted tabular-nums">{rows.length}</span>
      </h2>
      <ul>{all ? rows : rows.slice(0, LIMIT)}</ul>
      {rows.length > LIMIT ? (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="mx-2 min-h-11 rounded-lg px-2 text-[13px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          {all ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      ) : null}
    </section>
  );
}

export function CoursePage({ code, calendar, emails, onBack, onOpenEmail }: CoursePageProps) {
  const today = calendar.todayKey;
  const hue = calendar.courses.find((course) => course.code === code)?.hue;

  const deadlines = calendar.deadlines.filter((item) => item.course === code && !item.personal);
  const upcoming = deadlines.filter((item) => item.date >= today);
  const past = deadlines.filter((item) => item.date < today).reverse();

  const related = emails.filter((email) => courseCode(email) === code);
  const newestFirst = (a: InboxEmail, b: InboxEmail) =>
    Date.parse(b.receivedAt) - Date.parse(a.receivedAt);
  const announcements = related
    .filter((email) => isCanvasEmail(email) && !email.deadline)
    .sort(newestFirst);
  const people = related.filter((email) => !isCanvasEmail(email)).sort(newestFirst);

  const deadlineRow = (item: (typeof deadlines)[number]) => {
    const when = relativeDay(item.date, today);
    return (
      <li key={item.id}>
        <button type="button" onClick={() => onOpenEmail(item.emailId)} className={ROW}>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[14px] font-medium text-ink">
              {titleWithoutCourse(item.subject)}
            </span>
            <span className="mt-0.5 flex min-w-0 gap-x-2 text-[13px]">
              <span
                className={`shrink-0 font-semibold ${
                  when.tone === "overdue" ? "text-action-now-fg" : "text-highlight-dark"
                }`}
              >
                {when.text}
              </span>
              <span className="truncate text-muted">
                {formatDayShort(item.date)}, {formatTime(item.time)}
              </span>
            </span>
          </span>
        </button>
      </li>
    );
  };

  const mailRow = (email: InboxEmail) => (
    <li key={email.id}>
      <button type="button" onClick={() => onOpenEmail(email.id)} className={ROW}>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-medium text-ink">
            {titleWithoutCourse(email.subject)}
          </span>
          <span className="block truncate text-[13px] text-muted">{email.sender.name}</span>
        </span>
        <span className="shrink-0 pt-0.5 text-[12px] text-muted">
          {formatListDate(email.receivedAt)}
        </span>
      </button>
    </li>
  );

  const empty = deadlines.length + announcements.length + people.length === 0;

  return (
    <div className="flex flex-1 flex-col lg:min-h-0 lg:overflow-y-auto">
      <main className="mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-4 px-4 py-6 sm:px-6 lg:py-8">
        <header>
          <button
            type="button"
            onClick={onBack}
            className="-ml-2 inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-[13px] font-medium text-accent hover:bg-accent-soft focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back
          </button>
          <div className="mt-1 flex items-center gap-3">
            <h1 className="text-[24px] font-semibold tracking-[-0.015em] text-ink">{code}</h1>
            <CourseToken code={code} hue={hue} />
          </div>
          <p className="mt-1 text-[14px] text-muted">
            {upcoming.length} upcoming · {announcements.length} announcement
            {announcements.length === 1 ? "" : "s"} · {people.length} from people
          </p>
        </header>

        <Block title="Upcoming deadlines" rows={upcoming.map(deadlineRow)} />
        <Block title="Announcements" rows={announcements.map(mailRow)} />
        <Block title="From people" rows={people.map(mailRow)} />
        <Block title="Past deadlines" rows={past.map(deadlineRow)} />

        {empty ? (
          <p className="rounded-xl border border-line bg-surface px-5 py-8 text-center text-[14px] text-muted">
            Nothing found for {code} in the mail you have loaded.
          </p>
        ) : null}
      </main>
    </div>
  );
}
