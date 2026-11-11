import type { DeadlineCandidate } from "../domain/email";

const LOCALE = "en-SG";
const TIME_ZONE = "Asia/Singapore";

const listDate = new Intl.DateTimeFormat(LOCALE, {
  day: "numeric",
  month: "short",
  timeZone: TIME_ZONE,
});

const fullDate = new Intl.DateTimeFormat(LOCALE, {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZone: TIME_ZONE,
});

const deadlineDay = new Intl.DateTimeFormat(LOCALE, {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: TIME_ZONE,
});

function parseDate(value: string): Date | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Compact date used in the list, e.g. "5 Nov". */
export function formatListDate(iso: string): string {
  const date = parseDate(iso);
  return date ? listDate.format(date) : "—";
}

/** Full timestamp used in the detail pane, e.g. "Thu, 5 Nov 2026, 9:12 am SGT". */
export function formatFullDate(iso: string): string {
  const date = parseDate(iso);
  return date ? `${fullDate.format(date)} SGT` : "Unknown date";
}

export function formatDeadline(deadline: DeadlineCandidate): string {
  const date = parseDate(`${deadline.date}T${deadline.time ?? "00:00"}:00+08:00`);

  if (!date) {
    return `${deadline.date} ${deadline.timezone}`.trim();
  }

  if (!deadline.time) {
    return `${deadlineDay.format(date)} (all day) ${deadline.timezone}`;
  }

  return `${fullDate.format(date)} ${deadline.timezone}`;
}

const listTime = new Intl.DateTimeFormat(LOCALE, {
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZone: TIME_ZONE,
});

const dayKeyFormat = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: TIME_ZONE,
});

const groupWeekday = new Intl.DateTimeFormat(LOCALE, {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

const groupDate = new Intl.DateTimeFormat(LOCALE, {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

const groupDateYear = new Intl.DateTimeFormat(LOCALE, {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** Time of day used in the list, e.g. "10:42 am". */
export function formatListTime(iso: string): string {
  const date = parseDate(iso);
  return date ? listTime.format(date) : "—";
}

/** The Singapore calendar day an email arrived, as YYYY-MM-DD. */
export function emailDayKey(iso: string): string {
  const date = parseDate(iso);
  return date ? dayKeyFormat.format(date) : "unknown";
}

/** Heading for a day of mail: "Today", "Yesterday", "Mon, 10 Nov", "10 Nov" or "10 Nov 2025". */
export function formatDayHeading(dayKey: string, today: string): string {
  if (dayKey === "unknown") return "Unknown date";
  const day = Date.parse(`${dayKey}T00:00:00Z`);
  const now = Date.parse(`${today}T00:00:00Z`);
  if (Number.isNaN(day) || Number.isNaN(now)) return dayKey;
  const diff = Math.round((now - day) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff > 1 && diff < 7) return groupWeekday.format(day);
  if (dayKey.slice(0, 4) === today.slice(0, 4)) return groupDate.format(day);
  return groupDateYear.format(day);
}
