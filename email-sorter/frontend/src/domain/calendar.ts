import { assignCourseHues, courseCode, isCanvasEmail } from "./course";
import { bestLink } from "./links";
import type { EmailLink } from "./links";
import type { InboxEmail } from "./email";
import type { ActionKey, CategoryKey } from "./taxonomy";

const TODAY_FORMAT = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "Asia/Singapore",
});

/** Today as YYYY-MM-DD in Singapore, matching how deadlines are read. */
export function todayKey(now: Date = new Date()): string {
  return TODAY_FORMAT.format(now);
}

/**
 * A deadline candidate promoted to a read-only calendar item.
 *
 * Nothing here is a real calendar event: it is derived from the date the
 * backend found in an email. Nothing is written anywhere.
 */
export interface CalendarDeadline {
  id: string;
  emailId: string;
  date: string;
  time?: string;
  label: string;
  timezone: string;
  subject: string;
  sender: string;
  category?: CategoryKey;
  action?: ActionKey;
  /** Course code such as "DSS5105", only for Canvas coursework. */
  course?: string;
  /** Hue (0-359) shared by every item of the same course. */
  hue?: number;
  /** Best link found in the source email, such as the Canvas page. */
  link?: EmailLink;
  /** Set for events the student added; they have no source email. */
  personal?: PersonalEvent;
  /**
   * Done/snooze key when an email holds several dates. The first date uses the
   * email id, so it stays in step with the same mail in the Inbox.
   */
  stateKey?: string;
}

/** An event the student added by hand. */
export interface PersonalEvent {
  id: string;
  title: string;
  date: string;
  /** HH:mm, or empty for all day. */
  time: string;
  notes: string;
}

export type PersonalEventDraft = Omit<PersonalEvent, "id">;

/** One row of the shared NUS academic calendar (GET /api/academic-calendar). */
export interface AcademicEvent {
  category: string;
  event: string;
  startDate: string;
  endDate: string;
  notes: string;
  /** The CSV flags ranges whose start and end days should be labelled. */
  mark: boolean;
}

export interface MonthCell {
  date: string;
  day: number;
  inMonth: boolean;
  isWeekend: boolean;
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const LONG_DATE = new Intl.DateTimeFormat("en-SG", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

// The calendar's side panel sits next to the month grid, which already shows
// the year: "Wednesday, 4 Nov".
const PANEL_DATE = new Intl.DateTimeFormat("en-SG", {
  weekday: "long",
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

const SHORT_DATE = new Intl.DateTimeFormat("en-SG", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function toUtcDate(date: string): Date {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function toDateKey(date: Date): string {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(
    date.getUTCDate(),
  )}`;
}

export function buildDeadlines(
  emails: readonly InboxEmail[],
  personal: readonly PersonalEvent[] = [],
): CalendarDeadline[] {
  const courseOf = new Map<string, string>();

  for (const email of emails) {
    if (email.deadline && isCanvasEmail(email)) {
      const code = courseCode(email);
      if (code) {
        courseOf.set(email.id, code);
      }
    }
  }

  const hues = assignCourseHues([...courseOf.values()]);

  return emails
    .flatMap<CalendarDeadline>((email) => {
      const found = email.deadlines?.length
        ? email.deadlines
        : email.deadline
          ? [email.deadline]
          : [];

      return found.map((deadline, index) => ({
        id: index === 0 ? `deadline-${email.id}` : `deadline-${email.id}-${index + 1}`,
        stateKey: index === 0 ? undefined : `${email.id}#${index + 1}`,
        emailId: email.id,
        date: deadline.date,
        time: deadline.time,
        label: deadline.label,
        timezone: deadline.timezone,
        subject: email.subject,
        sender: email.sender.name,
        category: email.classification?.category,
        action: email.classification?.action,
        link: bestLink(email),
        course: courseOf.get(email.id),
        hue: hues.get(courseOf.get(email.id) ?? ""),
      }));
    })
    .concat(
      personal.map((event) => ({
        id: `personal-${event.id}`,
        emailId: "",
        date: event.date,
        time: event.time || undefined,
        label: "My event",
        timezone: "SGT",
        subject: event.title,
        sender: "You",
        personal: event,
      })),
    )
    .sort(
      (a, b) =>
        a.date.localeCompare(b.date) ||
        (a.time ?? "00:00").localeCompare(b.time ?? "00:00") ||
        a.id.localeCompare(b.id),
    );
}

export function academicEventsOn(
  events: readonly AcademicEvent[],
  date: string,
): AcademicEvent[] {
  return events.filter(
    (event) => event.startDate <= date && date <= event.endDate,
  );
}

/** Distinct courses in the calendar, for the legend. */
export function courseLegend(
  deadlines: readonly CalendarDeadline[],
): { code: string; hue: number }[] {
  const seen = new Map<string, number>();

  for (const deadline of deadlines) {
    if (deadline.course && deadline.hue !== undefined) {
      seen.set(deadline.course, deadline.hue);
    }
  }

  return [...seen.entries()]
    .map(([code, hue]) => ({ code, hue }))
    .sort((a, b) => a.code.localeCompare(b.code));
}

/** Monday of the week containing ``date`` (weeks run Monday to Sunday). */
export function startOfWeek(date: string): string {
  const weekday = (toUtcDate(date).getUTCDay() + 6) % 7;
  return addDays(date, -weekday);
}

export function daysBetween(from: string, to: string): number {
  return Math.round(
    (toUtcDate(to).getTime() - toUtcDate(from).getTime()) / 86_400_000,
  );
}

export type Urgency = "overdue" | "soon" | "later";

/** "Today", "Tomorrow", "In 3 days", "2 days overdue", plus a tone for color. */
export function relativeDay(
  date: string,
  today: string,
): { text: string; tone: Urgency } {
  const diff = daysBetween(today, date);

  if (diff < -1) return { text: `${-diff} days overdue`, tone: "overdue" };
  if (diff === -1) return { text: "Yesterday", tone: "overdue" };
  if (diff === 0) return { text: "Today", tone: "soon" };
  if (diff === 1) return { text: "Tomorrow", tone: "soon" };
  return { text: `In ${diff} days`, tone: "later" };
}

export function monthKeyOf(date: string): string {
  return date.slice(0, 7);
}

export function monthTitle(monthKey: string): string {
  const [year, month] = monthKey.split("-").map(Number);
  return `${MONTH_NAMES[month - 1]} ${year}`;
}

export function shiftMonth(monthKey: string, delta: number): string {
  const [year, month] = monthKey.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1 + delta, 1));
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}`;
}

export function addDays(date: string, days: number): string {
  const shifted = toUtcDate(date);
  shifted.setUTCDate(shifted.getUTCDate() + days);
  return toDateKey(shifted);
}

/**
 * Sunday-first month grid. Includes leading and trailing days from adjacent
 * months so every week row is full.
 */
export function buildMonthCells(monthKey: string): MonthCell[] {
  const [year, month] = monthKey.split("-").map(Number);
  const first = new Date(Date.UTC(year, month - 1, 1));
  const leadingDays = first.getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const totalCells = Math.ceil((leadingDays + daysInMonth) / 7) * 7;

  return Array.from({ length: totalCells }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1, 1 - leadingDays + index));
    const weekday = date.getUTCDay();

    return {
      date: toDateKey(date),
      day: date.getUTCDate(),
      inMonth: date.getUTCMonth() === month - 1,
      isWeekend: weekday === 0 || weekday === 6,
    };
  });
}

export function formatDayLong(date: string): string {
  return LONG_DATE.format(toUtcDate(date));
}

export function formatDayPanel(date: string): string {
  return PANEL_DATE.format(toUtcDate(date));
}

export function formatDayShort(date: string): string {
  return SHORT_DATE.format(toUtcDate(date));
}

export function formatTime(time?: string): string {
  if (!time) {
    return "All day";
  }

  const [hour, minute] = time.split(":").map(Number);
  const suffix = hour >= 12 ? "pm" : "am";
  return `${hour % 12 || 12}:${pad(minute)}${suffix}`;
}

/** Neutral count label: calendar items are a mix of appointments, deadlines, and social dates. */
export function formatItemCount(count: number): string {
  return `${count} ${count === 1 ? "item" : "items"}`;
}
