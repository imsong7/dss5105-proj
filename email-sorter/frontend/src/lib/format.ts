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

const shortDay = new Intl.DateTimeFormat(LOCALE, {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: TIME_ZONE,
});

/** A calendar day such as "Fri, 20 Nov", from "2026-11-20". */
export function formatShortDay(isoDay: string): string {
  const date = parseDate(`${isoDay}T12:00:00Z`);
  return date ? shortDay.format(date) : isoDay;
}

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
