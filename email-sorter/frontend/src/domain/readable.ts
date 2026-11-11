/**
 * Make email text easier to scan, for display only:
 * bullet lines become lists, short all-caps lines become headings,
 * "Venue: MPSH 2" lines get a bold label, and dates and times are marked.
 */

export type Block =
  | { kind: "p"; text: string }
  | { kind: "h"; text: string }
  | { kind: "ul" | "ol"; items: string[] };

const BULLET = /^\s*(?:[-•*·▪●◦–]|•)\s+/;
const NUMBERED = /^\s*(?:\d{1,2}|[a-z])[.)]\s+/;

function isHeading(line: string): boolean {
  const text = line.trim();
  if (text.length < 3 || text.length > 48 || /[.!?]$/.test(text)) return false;
  const letters = text.replace(/[^A-Za-z]/g, "");
  if (letters.length < 3) return false;
  const upper = letters.replace(/[^A-Z]/g, "").length;
  // "IMPORTANT", "EVENT DETAILS", or a short line ending in a colon: "What to bring:".
  return upper / letters.length >= 0.8 || (/:$/.test(text) && text.split(/\s+/).length <= 5);
}

function listKind(line: string): "ul" | "ol" | null {
  if (BULLET.test(line)) return "ul";
  if (NUMBERED.test(line)) return "ol";
  return null;
}

function stripMarker(line: string): string {
  return line.replace(BULLET, "").replace(NUMBERED, "").trim();
}

/** Paragraphs -> blocks. Consecutive bullet lines (even across paragraphs) form one list. */
export function toBlocks(paragraphs: readonly string[]): Block[] {
  const blocks: Block[] = [];
  const pushItem = (kind: "ul" | "ol", item: string) => {
    const last = blocks.at(-1);
    if (last && last.kind === kind) last.items.push(item);
    else blocks.push({ kind, items: [item] });
  };

  for (const paragraph of paragraphs) {
    const lines = paragraph.split("\n").map((line) => line.trim()).filter(Boolean);
    let text: string[] = [];
    const flush = () => {
      if (text.length) blocks.push({ kind: "p", text: text.join("\n") });
      text = [];
    };
    for (const [index, line] of lines.entries()) {
      const kind = listKind(line);
      if (kind) {
        flush();
        pushItem(kind, stripMarker(line));
      } else if (index === 0 && lines.length === 1 && isHeading(line)) {
        flush();
        blocks.push({ kind: "h", text: line.replace(/:$/, "") });
      } else {
        text.push(line);
      }
    }
    flush();
  }
  return blocks;
}

/** "Venue: MPSH 2" -> ["Venue", "MPSH 2"]; anything else -> null. */
export function labelValue(line: string): [string, string] | null {
  const found = /^([A-Z][A-Za-z /&()-]{1,22}):\s+(\S.*)$/.exec(line.trim());
  return found && !/^https?$/i.test(found[1]) ? [found[1], found[2]] : null;
}

const MONTH = "(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)";
const WEEKDAY = "(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?";
const CLOCK = "\\d{1,2}(?:[:.]\\d{2})?\\s?(?:am|pm)|\\d{1,2}:\\d{2}(?:\\s?(?:hrs|h))?";
/** Dates and times worth catching the eye: "Fri, 13 Nov 2026", "11:59pm", "2pm - 5pm". */
export const WHEN = new RegExp(
  `\\b(?:${WEEKDAY},?\\s+)?\\d{1,2}(?:st|nd|rd|th)?\\s+${MONTH}\\b(?:\\s+\\d{4})?` +
    `|\\b${MONTH}\\s+\\d{1,2}(?:st|nd|rd|th)?\\b(?:,?\\s+\\d{4})?` +
    `|\\b(?:${CLOCK})(?:\\s?[-–]\\s?(?:${CLOCK}))?` +
    `|\\b(?:today|tonight|tomorrow)\\b`,
  "gi",
);

/** Text split into plain parts and parts to mark (dates and times). */
export function markWhen(text: string): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  let last = 0;
  for (const found of text.matchAll(WHEN)) {
    const start = found.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start), mark: false });
    parts.push({ text: found[0], mark: true });
    last = start + found[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), mark: false });
  return parts;
}
