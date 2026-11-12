import type { EmailPriority } from "./email";

const CONSEQUENCE = [
  "Nothing happens if you ignore it",
  "A minor loss if you miss it",
  "Affects your grades, coursework or an opportunity",
  "Serious if you miss it (a penalty, a place, an offer or your standing)",
];

const URGENCY = [
  "No time pressure",
  "Due within a month",
  "Due within a week",
  "Due within 2 days, today or overdue",
];

const RELEVANCE = [
  "Mass marketing",
  "Sent to a large list",
  "Sent to your group or course",
  "About you personally",
];

/** Why a rule changed the stars, in plain words. */
const NOTES: Record<string, string> = {
  "serious and due soon": "Raised to at least 4: serious and due soon",
  "mass marketing cap": "Capped at 3: mass marketing",
  "possible phishing": "Capped at 2: possible phishing",
};

function pick(list: readonly string[], value: number | undefined): string | null {
  return value === undefined || value === null || !list[value] ? null : list[value];
}

/**
 * The reasons behind an email's stars, one short line each. They come from the same
 * numbers the stars are worked out from, so the explanation always matches the result.
 */
export function explainPriority(priority: EmailPriority): string[] {
  const lines: string[] = [];
  if (priority.keyPoint) {
    lines.push(priority.keyPoint);
  }
  for (const line of [
    pick(CONSEQUENCE, priority.consequence),
    pick(URGENCY, priority.urgency),
    pick(RELEVANCE, priority.relevance),
  ]) {
    if (line) lines.push(line);
  }
  for (const note of priority.notes) {
    lines.push(NOTES[note] ?? note);
  }
  if (priority.manual) {
    lines.push(
      priority.modelStars === undefined
        ? "You set this priority yourself."
        : `You set this priority yourself (it was rated ${priority.modelStars}).`,
    );
  }
  return lines;
}
