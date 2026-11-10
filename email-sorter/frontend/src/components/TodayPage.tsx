import { useEffect, useRef, useState } from "react";
import {
  Check,
  Circle,
  Clock,
  ExternalLink,
  Loader2,
  Moon,
  Pencil,
  Sun,
  Sunrise,
  Sunset,
} from "lucide-react";

import type { CalendarDeadline } from "../domain/calendar";
import {
  addDays,
  formatDayShort,
  formatTime,
  relativeDay,
} from "../domain/calendar";
import { titleWithoutCourse } from "../domain/course";
import type { InboxEmail } from "../domain/email";
import { senderInitials } from "../domain/inbox";
import { buildToday, countToday, isEmptyToday, itemKey } from "../domain/today";
import type { CalendarView } from "../hooks/useCalendarView";
import type { InboxView } from "../hooks/useInboxView";
import type { ItemStates } from "../hooks/useItemStates";
import { academicNote, termWeek } from "../domain/academic";
import { firstName, PERIODS, periodOf } from "../lib/greeting";
import { courseStyle } from "../domain/course";
import { useOpenCourse } from "../contexts/CourseContext";
import { CourseToken } from "./CourseToken";
import { useTheme } from "../hooks/useTheme";
import { Confetti } from "./Confetti";
import { LionMark } from "./LionMark";
import type { Mood } from "./LionMark";
import { WorkloadStrip } from "./WorkloadStrip";
import { SkeletonRows } from "./Skeleton";
import { Popover } from "./Popover";
import { SwipeRow } from "./SwipeRow";

interface TodayPageProps {
  inbox: InboxView;
  calendar: CalendarView;
  states: ItemStates;
  /** Display name from sign-up or the app; empty falls back to the email. */
  name: string;
  onEditName: () => void;
  mood: Mood;
  initials: string;
  onOpenAccount: () => void;
  onOpenEmail: (id: string) => void;
  onOpenDate: (date: string) => void;
}

const ROW =
  "flex min-h-11 min-w-0 flex-1 items-start gap-3 rounded-[10px] px-2 py-2.5 text-left transition-colors hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none";

const ICON_BUTTON =
  "grid h-11 w-11 shrink-0 place-items-center rounded-[10px] text-muted transition-colors hover:bg-surface-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none";

const SECTION_LIMIT = 5;

/** "DSS5105 final exam on 24 Nov 2026 9am" -> "DSS5105 final exam". */
function examName(subject: string): string {
  const cut = subject.split(/\s+(?:on|at|is|will|-|–|:)\s+|,/i)[0].trim();
  return cut.length > 2 ? cut : subject;
}
const BURST = [0, 45, 90, 135, 180, 225, 270, 315];

const TONE_CLASS = {
  overdue: "text-action-now-fg",
  soon: "text-highlight-dark",
  later: "text-muted",
} as const;

const PERIOD_ICONS = {
  morning: Sunrise,
  afternoon: Sun,
  evening: Sunset,
  night: Moon,
} as const;


/** Re-reads the clock so the banner changes if the page stays open. */
function usePeriod() {
  const [period, setPeriod] = useState(() => periodOf());

  useEffect(() => {
    const timer = window.setInterval(() => setPeriod(periodOf()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  return period;
}

function Section({
  title,
  tone = "",
  items,
}: {
  title: string;
  tone?: string;
  items: React.ReactNode[];
}) {
  const [all, setAll] = useState(false);

  if (items.length === 0) {
    return null;
  }

  const shown = all ? items : items.slice(0, SECTION_LIMIT);

  return (
    <section className="lift rounded-xl border border-line bg-surface p-2 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <h2 className="flex items-baseline gap-2 px-2 pt-2 pb-1 text-[14px] font-semibold text-ink">
        <span className={tone}>{title}</span>
        <span className="text-[12px] font-medium text-muted tabular-nums">
          {items.length}
        </span>
      </h2>
      <ul className="stagger">{shown}</ul>
      {items.length > SECTION_LIMIT ? (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="mx-2 min-h-11 rounded-lg px-2 text-[13px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          {all ? "Show fewer" : `Show all ${items.length}`}
        </button>
      ) : null}
    </section>
  );
}

function SnoozeMenu({
  today,
  onSnooze,
}: {
  today: string;
  onSnooze: (until: string) => void;
}) {
  const options = [
    { label: "Tomorrow", date: addDays(today, 1) },
    { label: "In 3 days", date: addDays(today, 3) },
    { label: "Next week", date: addDays(today, 7) },
  ];

  return (
    <Popover
      ariaLabel="Snooze"
      align="right"
      buttonClassName="w-11 justify-center border-transparent bg-transparent px-0 shadow-none"
      label={<Clock className="h-4 w-4 text-muted" aria-hidden="true" />}
    >
      {(close) => (
        <div>
          <p className="px-2.5 pb-1 text-[12px] font-medium text-muted">
            Hide until…
          </p>
          {options.map((option) => (
            <button
              key={option.date}
              type="button"
              onClick={() => {
                onSnooze(option.date);
                close();
              }}
              className="flex min-h-11 w-full items-center justify-between rounded-lg px-2.5 text-left text-[14px] text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              {option.label}
              <span className="text-[12px] text-muted">
                {formatDayShort(option.date)}
              </span>
            </button>
          ))}
        </div>
      )}
    </Popover>
  );
}

interface RowActions {
  hiddenLabel: string | null;
  onDone: () => void;
  onRestore: () => void;
  onSnooze: (until: string) => void;
  today: string;
}

function Actions({
  actions,
  children,
}: {
  actions: RowActions;
  children: React.ReactNode;
}) {
  const { hiddenLabel, onDone, onRestore, onSnooze, today } = actions;
  const [leaving, setLeaving] = useState(false);
  const [bursting, setBursting] = useState(false);

  // Let the row slide away before it is removed, so the change is visible.
  function leave(action: () => void) {
    setLeaving(true);
    window.setTimeout(action, 380);
  }

  return (
    <li
      className={`transition-all duration-300 ${
        leaving ? "-translate-x-3 opacity-0" : hiddenLabel ? "opacity-70" : ""
      }`}
    >
      <SwipeRow
        className="flex items-start"
        onSwipeRight={hiddenLabel ? undefined : onDone}
        rightLabel="Done"
        onSwipeLeft={
          hiddenLabel ? undefined : () => onSnooze(addDays(today, 1))
        }
        leftLabel="Snooze to tomorrow"
      >
        {hiddenLabel ? (
          <span
            className="grid h-11 w-11 shrink-0 place-items-center text-muted"
            aria-hidden="true"
          >
            <Check className="h-4 w-4" />
          </span>
        ) : (
          <button
            type="button"
            onClick={() => {
              setBursting(true);
              leave(onDone);
            }}
            aria-label="Mark done"
            title="Mark done"
            className={`${ICON_BUTTON} press group/done relative`}
          >
            {bursting ? (
              <span className="burst" aria-hidden="true">
                {BURST.map((angle, index) => (
                  <i
                    key={angle}
                    style={{
                      ["--a" as string]: `${angle}deg`,
                      background: index % 2 ? "#ef7c00" : "#003d7c",
                    }}
                  />
                ))}
              </span>
            ) : null}
            {bursting ? (
              <Check
                className="pop h-[18px] w-[18px] text-accent"
                aria-hidden="true"
              />
            ) : (
              <Circle
                className="h-[18px] w-[18px] transition-colors group-hover/done:text-accent"
                aria-hidden="true"
              />
            )}
          </button>
        )}
        {children}
        {hiddenLabel ? (
          <button
            type="button"
            onClick={onRestore}
            className="mt-0.5 min-h-11 shrink-0 rounded-[10px] px-3 text-[13px] font-medium text-accent hover:bg-accent-soft focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          >
            {hiddenLabel} · Restore
          </button>
        ) : (
          <SnoozeMenu
            today={today}
            onSnooze={(until) => leave(() => onSnooze(until))}
          />
        )}
      </SwipeRow>
    </li>
  );
}

function DeadlineRow({
  item,
  actions,
  onOpenEmail,
  onOpenDate,
}: {
  item: CalendarDeadline;
  actions: RowActions;
  onOpenEmail: (id: string) => void;
  onOpenDate: (date: string) => void;
}) {
  const title = item.course ? titleWithoutCourse(item.subject) : item.subject;
  const when = relativeDay(item.date, actions.today);

  return (
    <Actions actions={actions}>
      <button
        type="button"
        onClick={() =>
          item.personal ? onOpenDate(item.date) : onOpenEmail(item.emailId)
        }
        className={ROW}
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-medium text-ink">
            {title}
          </span>
          <span className="mt-0.5 flex min-w-0 items-center gap-x-2 text-[13px]">
            <span className={`shrink-0 font-semibold ${TONE_CLASS[when.tone]}`}>
              {when.text}
            </span>
            <span className="truncate text-muted">
              {formatDayShort(item.date)}, {formatTime(item.time)}
            </span>
            {item.course ? (
              <CourseToken code={item.course} hue={item.hue} />
            ) : null}
            {item.personal ? (
              <span className="shrink-0 text-muted">Your event</span>
            ) : null}
          </span>
        </span>
      </button>
      {item.link ? (
        <a
          href={item.link.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={item.link.label}
          title={item.link.label}
          className={ICON_BUTTON}
        >
          <ExternalLink className="h-4 w-4" aria-hidden="true" />
        </a>
      ) : null}
    </Actions>
  );
}

function MailRow({
  email,
  actions,
  onOpenEmail,
}: {
  email: InboxEmail;
  actions: RowActions;
  onOpenEmail: (id: string) => void;
}) {
  return (
    <Actions actions={actions}>
      <button
        type="button"
        onClick={() => onOpenEmail(email.id)}
        className={ROW}
      >
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-muted text-[12px] font-semibold text-ink/60"
          aria-hidden="true"
        >
          {senderInitials(email.sender.name)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-medium text-ink">
            {email.subject}
          </span>
          <span className="block truncate text-[13px] text-muted">
            {email.sender.name}
          </span>
        </span>
      </button>
    </Actions>
  );
}

export function TodayPage({
  inbox,
  calendar,
  states,
  name: chosenName,
  onEditName,
  mood,
  initials,
  onOpenAccount,
  onOpenEmail,
  onOpenDate,
}: TodayPageProps) {
  const openCourse = useOpenCourse();
  const today = calendar.todayKey;
  const [reveal, setReveal] = useState(false);
  const period = usePeriod();
  const { dark } = useTheme();
  const theme = dark
    ? { ...PERIODS.night, greeting: PERIODS[period].greeting }
    : PERIODS[period];
  const PeriodIcon = PERIOD_ICONS[period];
  const name = chosenName || firstName(inbox.session.email);
  const week = termWeek(calendar.academicAll, today);
  const note = academicNote(calendar.academicAll, today);

  // Not done, and not your own reminders: what the workload strip counts.
  const workloadItems = calendar.deadlines.filter(
    (item) => !states.isDone(itemKey(item)),
  );
  const exams = workloadItems
    .filter(
      (item) => item.label === "Exam" && !item.personal && item.date >= today,
    )
    .slice(0, 2);

  const visible = buildToday(calendar.deadlines, inbox.emails, today, (key) =>
    states.isHidden(key, today),
  );
  const everything = buildToday(calendar.deadlines, inbox.emails, today);
  const hiddenCount = countToday(everything) - countToday(visible);
  const sections = reveal ? everything : visible;

  // "Cleared this week": things marked done in the last 7 days, out of those
  // plus what is still due soon. Gives the student a sense of getting through it.
  const weekAgo = Date.now() - 7 * 86_400_000;
  const cleared = Object.values(states.states).filter(
    (state) => state.done && state.at && Date.parse(state.at) >= weekAgo,
  ).length;
  // Old overdue items do not count: the bar looks forward.
  const remaining = visible.today.length + visible.soon.length;
  const weekTotal = cleared + remaining;

  // Celebrate only when the student's own action empties the list.
  const [celebrate, setCelebrate] = useState(false);
  const lastRemaining = useRef<number | null>(null);
  useEffect(() => {
    const previous = lastRemaining.current;
    lastRemaining.current = inbox.hasLoaded ? remaining : null;
    if (
      previous !== null &&
      previous > 0 &&
      remaining === 0 &&
      inbox.hasLoaded
    ) {
      setCelebrate(true);
      const timer = window.setTimeout(() => setCelebrate(false), 2600);
      return () => window.clearTimeout(timer);
    }
  }, [remaining, inbox.hasLoaded]);

  // Still loading, or the flow is still sending mail: show only that.
  const busyLoading = inbox.loading || inbox.receiving;
  const sorting = busyLoading ? null : inbox.progress;
  const unsorted = inbox.pendingCount;
  // "Caught up" ignores old overdue items; they sit in their own collapsed list.
  const empty = isEmptyToday({ ...visible, overdue: [] });
  const [showOverdue, setShowOverdue] = useState(false);
  const needsOutlook = inbox.session.provider === "outlook" && !inbox.token;

  const summary = [
    visible.today.length ? `${visible.today.length} due today` : null,
    visible.reply.length ? `${visible.reply.length} need a reply` : null,
  ].filter(Boolean);

  const nextSoon = visible.soon[0];

  const dateLabel = new Intl.DateTimeFormat("en-SG", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "Asia/Singapore",
  }).format(new Date(`${today}T12:00:00Z`));

  function actionsFor(key: string): RowActions {
    const state = states.states[key];
    const hidden = states.isHidden(key, today);

    return {
      hiddenLabel: !hidden
        ? null
        : state?.done
          ? "Done"
          : `Snoozed to ${formatDayShort(state?.snoozedUntil ?? today)}`,
      onDone: () => void states.setDone(key, true),
      onRestore: () => void states.setDone(key, false),
      onSnooze: (until) => void states.snooze(key, until),
      today,
    };
  }

  const deadlineRows = (items: CalendarDeadline[]) =>
    items.map((item) => (
      <DeadlineRow
        key={item.id}
        item={item}
        actions={actionsFor(itemKey(item))}
        onOpenEmail={onOpenEmail}
        onOpenDate={onOpenDate}
      />
    ));

  const mailRows = (items: InboxEmail[]) =>
    items.map((email) => (
      <MailRow
        key={email.id}
        email={email}
        actions={actionsFor(email.id)}
        onOpenEmail={onOpenEmail}
      />
    ));

  return (
    <div className="flex flex-1 flex-col lg:min-h-0 lg:overflow-y-auto">
      <main className="mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-4 px-4 py-6 sm:px-6 lg:py-8 xl:max-w-[1180px]">
        <header
          style={{
            ["--banner-bg" as string]: theme.background,
            color: theme.ink,
          }}
          className="relative isolate flex items-center gap-4 overflow-hidden rounded-2xl px-4 py-5 transition-colors duration-500 [background:var(--banner-bg)] lg:overflow-visible lg:rounded-none lg:[background:none] lg:px-0 lg:pt-3 max-sm:-mx-4 max-sm:-mt-[calc(1.5rem+env(safe-area-inset-top))] max-sm:min-h-[40dvh] max-sm:flex-col max-sm:items-stretch max-sm:justify-end max-sm:gap-2 max-sm:rounded-t-none max-sm:rounded-b-[28px] max-sm:px-6 max-sm:pt-[calc(1.25rem+env(safe-area-inset-top))] max-sm:pb-6 sm:px-6"
        >
          {/* The lion lies right on the date line; extra banner height goes above it. */}
          <div className="-mb-3 sm:hidden">
            <LionMark size={104} mood={mood} />
          </div>
          <button
            type="button"
            onClick={onOpenAccount}
            aria-label="Account and settings"
            style={{ background: theme.iconBg, color: theme.iconFg }}
            className="press absolute top-[calc(1.25rem+env(safe-area-inset-top))] right-6 z-10 grid h-11 w-11 place-items-center rounded-full text-[13px] font-semibold focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none sm:hidden"
          >
            {initials}
          </button>
          <span
            style={{ background: theme.iconBg, color: theme.iconFg }}
            className="relative hidden h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-2xl sm:grid"
            aria-hidden="true"
          >
            <span
              className="icon-glow"
              style={{
                ["--glow" as string]: dark
                  ? "rgba(255,255,255,0.28)"
                  : "rgba(255,255,255,0.75)",
              }}
            />
            <PeriodIcon className="relative h-6 w-6" />
          </span>
          <div className="min-w-0">
            <p
              style={{ color: theme.muted }}
              className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]"
            >
              <span>
                {dateLabel}
                {week ? ` · Week ${week.week}` : ""}
              </span>
              {note ? (
                <span
                  style={{ background: "rgba(127,127,127,0.18)" }}
                  className="rounded-full px-2.5 py-0.5 text-[12px] font-medium"
                >
                  {note}
                </span>
              ) : null}
            </p>
            <h1 className="mt-0.5 text-[27px] leading-tight font-semibold tracking-[-0.015em] sm:text-[24px]">
              {theme.greeting}
              {name ? `, ${name}` : ""}
              <button
                type="button"
                onClick={onEditName}
                aria-label="Change your name"
                title="Change your name"
                style={{ color: theme.muted }}
                className="ml-1 inline-grid h-11 w-11 -translate-y-px place-items-center rounded-full align-middle opacity-70 hover:opacity-100 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </h1>
            <p style={{ color: theme.muted }} className="mt-1 text-[14px]">
              {summary.length
                ? summary.join(" · ")
                : inbox.hasLoaded
                  ? nextSoon
                    ? `Next: ${nextSoon.course ? titleWithoutCourse(nextSoon.subject) : nextSoon.subject} · ${relativeDay(nextSoon.date, today).text.toLowerCase()}`
                    : "Nothing urgent right now."
                  : needsOutlook
                    ? "Connect your mailbox to see what needs attention."
                    : "Load your mail to see what needs attention."}
            </p>
            {weekTotal > 0 && !busyLoading ? (
              <div className="mt-2.5 max-w-[320px]">
                <div
                  role="progressbar"
                  aria-label="Cleared this week"
                  aria-valuemin={0}
                  aria-valuemax={weekTotal}
                  aria-valuenow={cleared}
                  className="h-1.5 overflow-hidden rounded-full"
                  style={{ background: "rgba(127,127,127,0.25)" }}
                >
                  <div
                    className="h-full rounded-full bg-highlight transition-[width] duration-700 ease-out"
                    style={{ width: `${(cleared / weekTotal) * 100}%` }}
                  />
                </div>
                <p style={{ color: theme.muted }} className="mt-1 text-[13px]">
                  {cleared} of {weekTotal} cleared this week
                </p>
              </div>
            ) : null}
          </div>
        </header>

        <div className="flex flex-col gap-4 xl:grid xl:grid-cols-[minmax(0,1fr)_340px] xl:items-start xl:gap-6">
          {/* Overview first on phones; a side column on wide screens. */}
          <div className="flex flex-col gap-4 xl:sticky xl:top-4 xl:col-start-2 xl:row-start-1">
            <WorkloadStrip
              deadlines={calendar.deadlines}
              isDone={(key) => states.isDone(key)}
              academic={calendar.academicAll}
              today={today}
              onOpenDate={onOpenDate}
              onOpenEmail={onOpenEmail}
            />

            {calendar.courses.length > 0 ? (
              <ul aria-label="Your courses" className="flex flex-wrap gap-2">
                {calendar.courses.map((course) => (
                  <li key={course.code}>
                    <button
                      type="button"
                      onClick={() => openCourse?.(course.code)}
                      aria-label={`Open course ${course.code}`}
                      style={courseStyle(course.hue)}
                      className="press inline-flex min-h-11 items-center rounded-full bg-[var(--course-bg)] px-4 text-[13px] font-bold tracking-[0.04em] text-[var(--course-text)] hover:brightness-95 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                    >
                      {course.code}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}

            {exams.length > 0 ? (
              <ul aria-label="Exam countdown" className="flex flex-wrap gap-2">
                {exams.map((exam) => {
                  const when = relativeDay(exam.date, today);
                  return (
                    <li
                      key={exam.id}
                      className="inline-flex min-h-11 items-center gap-2 rounded-full border border-highlight-line bg-highlight-soft px-3.5 text-[13px] text-ink"
                    >
                      {exam.course ? (
                        <CourseToken code={exam.course} hue={exam.hue} />
                      ) : null}
                      <span className="max-w-[200px] truncate font-semibold">
                        {exam.course ? "Exam" : examName(exam.subject)}
                      </span>
                      <span className="shrink-0 text-highlight-dark">
                        {when.text.toLowerCase()}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
          <div className="flex min-w-0 flex-col gap-4 xl:col-start-1 xl:row-start-1">
            {busyLoading ? (
              <p
                role="status"
                className="flex items-center gap-2 text-[13px] text-accent"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading your mail…
              </p>
            ) : sorting ? (
              <p
                role="status"
                className="flex items-center gap-2 text-[13px] text-accent"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Sorting your mail… {sorting.done} / {sorting.total}
              </p>
            ) : null}

            {inbox.loading && !inbox.hasLoaded ? (
              <div className="overflow-hidden rounded-xl border border-line bg-surface">
                <SkeletonRows count={4} />
              </div>
            ) : null}

            {inbox.notice?.error ? (
              <p
                role="alert"
                className="rounded-[10px] border border-action-now-line bg-action-now-bg px-3.5 py-2.5 text-[13px] text-action-now-fg"
              >
                {inbox.notice.text}
              </p>
            ) : null}

            {states.error ? (
              <p role="alert" className="text-[13px] text-action-now-fg">
                {states.error}
              </p>
            ) : null}

            {inbox.hasLoaded &&
            !busyLoading &&
            unsorted > 0 &&
            !sorting &&
            (!inbox.autoSort || inbox.waitingForBatch) ? (
              <button
                type="button"
                onClick={() => void inbox.classifyPending()}
                className="min-h-11 self-start rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none"
              >
                Sort {unsorted} email{unsorted === 1 ? "" : "s"}
              </button>
            ) : null}
            {inbox.waitingForBatch && !sorting && !busyLoading ? (
              <p className="-mt-2 text-[13px] text-muted">
                Sorting starts by itself at {inbox.sortBatchSize} emails, or
                once mail stops arriving.
              </p>
            ) : null}

            <RowTip show={countToday(visible) > 0} />
            <Section title="Due today" items={deadlineRows(sections.today)} />
            <Section title="Next 7 days" items={deadlineRows(sections.soon)} />
            <Section title="Needs a reply" items={mailRows(sections.reply)} />
            <Section title="Needs action" items={mailRows(sections.action)} />

            {sections.overdue.length > 0 ? (
              showOverdue ? (
                <div className="flex flex-col gap-1">
                  <Section
                    title="Overdue"
                    tone="text-action-now-fg"
                    items={deadlineRows(sections.overdue)}
                  />
                  <button
                    type="button"
                    onClick={() => setShowOverdue(false)}
                    className="min-h-11 self-start rounded-lg px-1 text-[13px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                  >
                    Hide overdue
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowOverdue(true)}
                  className="min-h-11 self-start rounded-lg px-1 text-[13px] font-medium text-muted hover:text-ink hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                >
                  {sections.overdue.length} earlier item
                  {sections.overdue.length === 1 ? "" : "s"} overdue · Show
                </button>
              )
            ) : null}

            {hiddenCount > 0 ? (
              <button
                type="button"
                onClick={() => setReveal(!reveal)}
                className="min-h-11 self-start rounded-lg px-1 text-[13px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
              >
                {reveal ? "Hide" : "Show"} {hiddenCount} done or snoozed item
                {hiddenCount === 1 ? "" : "s"}
              </button>
            ) : null}

            {inbox.hasLoaded &&
            inbox.total > 0 &&
            empty &&
            !reveal &&
            !sorting &&
            unsorted === 0 ? (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-line bg-surface px-6 py-12 text-center">
                <LionMark size={80} mood="cheer" />
                <p className="text-[15px] font-semibold text-ink">
                  You are all caught up
                </p>
                <p className="max-w-[40ch] text-[14px] text-muted">
                  No deadlines this week and no mail waiting for a reply.
                </p>
              </div>
            ) : null}
          </div>
        </div>
      </main>
      {celebrate ? <Confetti /> : null}
    </div>
  );
}

const TIP_KEY = "inbox-sorter.tip-rows";

/** Shown once: what the circle, the clock and the swipe do. */
function RowTip({ show }: { show: boolean }) {
  const [seen, setSeen] = useState(() => {
    try {
      return window.localStorage.getItem(TIP_KEY) === "1";
    } catch {
      return false;
    }
  });
  const touch =
    typeof window !== "undefined" &&
    window.matchMedia("(pointer: coarse)").matches;

  if (!show || seen) {
    return null;
  }

  function dismiss() {
    setSeen(true);
    try {
      window.localStorage.setItem(TIP_KEY, "1");
    } catch {
      // It will show again next time; harmless.
    }
  }

  return (
    <div className="flex items-start gap-3 rounded-xl border border-accent/20 bg-accent-soft px-4 py-3">
      <p className="min-w-0 flex-1 text-[13px] leading-5 text-ink">
        {touch
          ? "Tip: swipe a row right when it is done, or left to hide it until tomorrow. The clock picks another day."
          : "Tip: tick the circle when something is done. The clock hides it until a day you choose."}
      </p>
      <button
        type="button"
        onClick={dismiss}
        className="min-h-11 shrink-0 rounded-lg px-2 text-[13px] font-semibold text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
      >
        Got it
      </button>
    </div>
  );
}
