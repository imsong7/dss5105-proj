/**
 * The few facts worth seeing before reading an email: where, which course
 * and a meeting link. Dates are not guessed here: an email can
 * hold several, so they are listed (with where each was found) in the date card.
 */

export type FactKind = "place" | "course" | "meeting";

export interface Fact {
  kind: FactKind;
  label: string;
  /** Where tapping the chip goes (NUSMods venue search, meeting link). */
  href?: string;
}

const MAX_FACTS = 6;

const VENUE_LABEL = /\b(?:venue|location|where|place|room)\s*[:\-–]\s*([^\n.;]{2,48})/i;
const VENUE_CODES =
  /\b(?:LT\s?\d{1,2}[A-Z]?|COM\s?[1-4]|SR\s?\d{1,2}|MPSH\s?\d?|E\d{1,2}[A-Z]?-\d{2}-\d{2}|S\d{1,2}[A-Z]?-\d{2}-\d{2}|AS\d-\d{2}-\d{2}|UTown|University Town|Yusof Ishak House|YIH|Central Library|Kent Ridge Hall|Stephen Riady Centre|Shaw Foundation Alumni House|Education Resource Centre|ERC|i3 Building|Innovation 4\.0)\b/i;
const COURSE = /\b[A-Z]{2,4}\d{4}[A-Z]{0,2}\b/g;
const MEETING = /https?:\/\/(?:[\w-]+\.)?(?:zoom\.us|teams\.microsoft\.com|meet\.google\.com|teams\.live\.com)\/[^\s<>")\]]+/i;
const NOT_COURSES = new Set(["COVID2019", "ISO9001"]);

function nusmods(venue: string): string | undefined {
  // NUSMods knows teaching venues by code (LT27, COM1-0204, E3-06-12, ...).
  return /^(?:LT|COM|SR|E\d|S\d|AS\d)/i.test(venue)
    ? `https://nusmods.com/venues/${encodeURIComponent(venue.replace(/\s+/g, ""))}`
    : undefined;
}

export function keyFacts(subject: string, text: string): Fact[] {
  const facts: Fact[] = [];
  const add = (fact: Fact) => {
    if (facts.length < MAX_FACTS && !facts.some((item) => item.label.toLowerCase() === fact.label.toLowerCase())) {
      facts.push(fact);
    }
  };
  const all = `${subject}\n${text}`;

  const labelled = VENUE_LABEL.exec(text);
  if (labelled) {
    const venue = labelled[1].trim().replace(/[,\s]+$/, "");
    add({ kind: "place", label: venue, href: nusmods(venue) });
  } else {
    const code = VENUE_CODES.exec(all);
    if (code) add({ kind: "place", label: code[0], href: nusmods(code[0]) });
  }

  const meeting = MEETING.exec(text);
  if (meeting) {
    const label = /zoom/i.test(meeting[0]) ? "Zoom" : /meet\.google/i.test(meeting[0]) ? "Google Meet" : "Teams";
    add({ kind: "meeting", label: `Join ${label}`, href: meeting[0] });
  }


  for (const found of all.matchAll(COURSE)) {
    if (!NOT_COURSES.has(found[0])) add({ kind: "course", label: found[0] });
  }

  return facts;
}
