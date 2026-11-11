import type { CSSProperties } from "react";

import type { InboxEmail } from "./email";

/** "DSS5105" style code found in the subject, body, or preview. */
export function courseCode(email: InboxEmail): string | null {
  const text = `${email.subject}\n${email.body}\n${email.preview}`;
  const match = text.match(/\b([A-Z]{2,5})\s?(\d{4,5}[A-Z]?)\b/i);

  return match ? `${match[1]}${match[2]}`.toUpperCase() : null;
}

/** Coursework mail comes from Canvas; ordinary mail must not get a course color. */
export function isCanvasEmail(email: InboxEmail): boolean {
  if (/canvas|instructure\.com/i.test(`${email.sender.name} ${email.sender.address}`)) {
    return true;
  }

  return /\bview\s+(assignment|announcement|discussion|quiz|exam(?:ination)?)\b/i.test(
    `${email.subject}\n${email.body}\n${email.preview}`,
  );
}

/** Drop a leading course code so "[DSS5105] DSS5105 final exam" is not repeated. */
export function titleWithoutCourse(subject: string): string {
  const cleaned = subject
    .replace(/^\s*#+\s*/, "")
    .replace(
      /^\s*(?:assignment|exam|examination|quiz|test|announcement)\s+(?:created|updated|published|posted)\s*[-:–—]\s*/i,
      "",
    )
    .trim();
  const withoutCode = cleaned
    .replace(/^[A-Z]{2,5}\s?\d{4,5}[A-Z]?\s*[-–—:·]?\s+/i, "")
    .trim();

  return withoutCode || cleaned || subject;
}

const COURSEWORK =
  /\b(?:assignment|quiz|exam(?:ination)?|test|tutorial|lecture|project|grade|grading|feedback|submission|submit|due|deadline|presentation|consultation|reading week|ca\d)\b/i;

/**
 * Course mail: from Canvas, or a course code next to a coursework word (the
 * same idea as the server's course rule). Ordinary mail stays uncoloured.
 */
export function isCourseEmail(email: InboxEmail): boolean {
  return isCanvasEmail(email) || (courseCode(email) !== null && COURSEWORK.test(email.subject));
}

/**
 * The task in a few words for tight spaces: "CA4 submission due Friday
 * 11:59pm, DSS5101 Principles of Sustainability" becomes "CA4 submission".
 * The date and course are shown next to it, so they are dropped here.
 */
export function shortTitle(subject: string): string {
  const base = titleWithoutCourse(subject);
  const short = base
    // ", DSS5101 Principles of ..." and anything after a course code
    .replace(/\s*[,(\[–—:-]?\s*\b[A-Z]{2,5}\s?\d{4,5}[A-Z]?\b.*$/, "")
    // "due Friday 11:59pm", "- register by 12 Nov", "deadline: ..."
    .replace(/\s*[-–—:,]?\s*\b(?:is\s+)?(?:due|deadline|register by|submit by|closes?)\b.*$/i, "")
    // "on 24 Nov 2026 9am"
    .replace(/\s+on\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,}.*$/i, "")
    .replace(/[\s,:;–—-]+$/, "")
    .trim();
  const chosen = short.length >= 3 ? short : base;

  return chosen.charAt(0).toUpperCase() + chosen.slice(1);
}

// Widely spaced hues so two courses never get near-identical colors. A stable
// hash picks a starting slot; collisions move to the next free slot.
const COURSE_HUES = [352, 22, 46, 76, 128, 158, 186, 210, 238, 264, 292, 320];
const HUE_GAP = 40;

function hash(code: string): number {
  let value = 2166136261;

  for (const character of code) {
    value ^= character.charCodeAt(0);
    value = Math.imul(value, 16777619);
  }

  return value >>> 0;
}

function hueGap(a: number, b: number): number {
  const distance = Math.abs(a - b) % 360;
  return Math.min(distance, 360 - distance);
}

export function assignCourseHues(codes: readonly string[]): Map<string, number> {
  const unique = [...new Set(codes)].sort();
  const used = new Set<number>();
  const result = new Map<string, number>();

  for (const code of unique) {
    const preferred = hash(code) % COURSE_HUES.length;
    let chosen: number | null = null;
    let fallback: number | null = null;
    let fallbackGap = -1;

    for (let step = 0; step < COURSE_HUES.length; step += 1) {
      const hue = COURSE_HUES[(preferred + step) % COURSE_HUES.length];

      if (used.has(hue)) {
        continue;
      }

      const gap = used.size
        ? Math.min(...[...used].map((other) => hueGap(hue, other)))
        : 360;

      if (gap >= HUE_GAP) {
        chosen = hue;
        break;
      }

      if (gap > fallbackGap) {
        fallbackGap = gap;
        fallback = hue;
      }
    }

    // More courses than well-spaced hues: take the most distant free hue.
    const hue = chosen ?? fallback ?? COURSE_HUES[preferred];
    used.add(hue);
    result.set(code, hue);
  }

  return result;
}

export function courseStyle(hue: number | undefined): CSSProperties | undefined {
  if (hue === undefined) {
    return undefined;
  }

  return {
    "--course-bg": `hsl(${hue} 82% var(--course-bg-l, 92%))`,
    "--course-border": `hsl(${hue} 64% 54%)`,
    "--course-text": `hsl(${hue} 68% var(--course-text-l, 24%))`,
    "--course-accent": `hsl(${hue} 72% var(--course-accent-l, 38%))`,
  } as CSSProperties;
}
