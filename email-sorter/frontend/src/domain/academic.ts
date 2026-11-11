import type { AcademicEvent } from "./calendar";
import { addDays, daysBetween } from "./calendar";

export type AcademicTone =
  | "holiday"
  | "exam"
  | "reading"
  | "vacation"
  | "orientation"
  | "semester";

export const ACADEMIC_TONES: Record<
  AcademicTone,
  { label: string; bg: string; ink: string; accent: string }
> = {
  holiday: { label: "Holiday", bg: "#fff1f0", ink: "#912018", accent: "#d92d20" },
  exam: { label: "Exams", bg: "#fff6e8", ink: "#93370d", accent: "#dc6803" },
  reading: { label: "Reading week", bg: "#eef6ff", ink: "#175cd3", accent: "#2e90fa" },
  vacation: { label: "Vacation", bg: "#ecfbf2", ink: "#067647", accent: "#12b76a" },
  orientation: { label: "Orientation", bg: "#f4f1ff", ink: "#5925dc", accent: "#7a5af8" },
  semester: { label: "Term", bg: "#f2f4f7", ink: "#475467", accent: "#98a2b3" },
};

export function academicTone(category: string): AcademicTone {
  const text = category.toLowerCase();

  if (text.includes("holiday")) return "holiday";
  if (text.includes("exam")) return "exam";
  if (text.includes("reading")) return "reading";
  if (text.includes("vacation")) return "vacation";
  if (text.includes("orientation")) return "orientation";
  return "semester";
}

/** Short label for a tight calendar cell, e.g. "Sem 1" or "1A Exam". */
export function academicShortTitle(event: AcademicEvent): string {
  return event.event
    .replace(/^Mini Semester\s+/i, "")
    .replace(/\bExamination\b/gi, "Exam")
    .replace(/\bVacation\b/gi, "Vac")
    .replace(/^Semester\s+(\d)/i, "Sem $1")
    .replace(/^Special Term Part\s+/i, "Special Term ");
}

export interface AcademicMarker {
  event: AcademicEvent;
  tone: AcademicTone;
  /** "day" for one-day events; "start"/"end" label the edges of a range. */
  edge: "day" | "start" | "end";
}

/**
 * Markers shown inside a day cell. Ranges would fill the whole grid, so only a
 * range's first and last day get a marker, and only when the CSV flags it.
 */
export function academicMarkersOn(
  events: readonly AcademicEvent[],
  date: string,
): AcademicMarker[] {
  const markers: AcademicMarker[] = [];

  for (const event of events) {
    const tone = academicTone(event.category);

    if (event.startDate === event.endDate) {
      if (event.startDate === date) {
        markers.push({ event, tone, edge: "day" });
      }
    } else if (event.mark && event.startDate === date) {
      markers.push({ event, tone, edge: "start" });
    } else if (event.mark && event.endDate === date) {
      markers.push({ event, tone, edge: "end" });
    }
  }

  return markers;
}

/** Short text for a day cell: ▸ marks the first day of a range, ◂ the last. */
export function markerLabel(marker: AcademicMarker): string {
  const title = academicShortTitle(marker.event);

  return marker.edge === "start"
    ? `▸ ${title}`
    : marker.edge === "end"
      ? `${title} ◂`
      : title;
}

/** The same label in words, for screen readers. */
export function markerSpoken(marker: AcademicMarker): string {
  const title = academicShortTitle(marker.event);

  return marker.edge === "start"
    ? `${title} starts`
    : marker.edge === "end"
      ? `${title} ends`
      : title;
}

export function upcomingAcademic(
  events: readonly AcademicEvent[],
  after: string,
  limit: number,
): AcademicEvent[] {
  return events.filter((event) => event.startDate > after).slice(0, limit);
}

/** "Semester 1, week 12" for a date inside a regular semester, else ``null``. */
export function termWeek(
  events: readonly AcademicEvent[],
  date: string,
): { term: string; week: number } | null {
  const term = events.find(
    (event) =>
      academicTone(event.category) === "semester" &&
      /^semester\s+\d/i.test(event.event) &&
      event.startDate <= date &&
      date <= event.endDate,
  );

  return term
    ? { term: term.event, week: Math.floor(daysBetween(term.startDate, date) / 7) + 1 }
    : null;
}

const WEEKDAY = new Intl.DateTimeFormat("en-SG", { weekday: "long", timeZone: "UTC" });

/** "today", "tomorrow" or "in 4 days": how far away a date is. */
function daysAway(date: string, today: string): string {
  const diff = daysBetween(today, date);

  if (diff <= 0) return "today";
  if (diff === 1) return "tomorrow";
  return `in ${diff} days`;
}

/**
 * One short line about the academic calendar: what is on now, or what starts
 * soon. Term and public-holiday rows are skipped; they are not a "heads up".
 */
export function academicNote(
  events: readonly AcademicEvent[],
  today: string,
  lookAheadDays = 10,
): string | null {
  const notable = events.filter((event) => {
    const tone = academicTone(event.category);
    return tone !== "semester";
  });

  const ongoing = notable.find(
    (event) =>
      event.startDate < today &&
      today <= event.endDate &&
      event.endDate !== event.startDate,
  );
  if (ongoing) {
    return `${ongoing.event} until ${WEEKDAY.format(new Date(`${ongoing.endDate}T12:00:00Z`))}`;
  }

  const soon = notable.find(
    (event) =>
      event.startDate >= today && event.startDate <= addDays(today, lookAheadDays),
  );
  if (!soon) {
    return null;
  }

  // A one-day event simply "is" on that day; a longer one "starts".
  const verb = soon.endDate === soon.startDate ? "is" : "starts";
  return `${soon.event} ${verb} ${daysAway(soon.startDate, today)}`;
}
