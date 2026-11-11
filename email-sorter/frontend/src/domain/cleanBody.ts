/**
 * Split an email's paragraphs into what the student needs to read and what
 * can fold away: earlier messages quoted in a reply, and the signature,
 * disclaimers and notification boilerplate at the end.
 *
 * Display only: the full text still goes to sorting and date finding.
 */

interface CleanBody {
  /** Paragraphs to show. */
  main: string[];
  /** Signature, disclaimers, "you received this because", unsubscribe. */
  footer: string[];
  /** Older messages quoted below a reply. */
  earlier: string[];
}

// Where a quoted older message starts.
const QUOTE_START = [
  /^On .{6,120} wrote:\s*$/im,
  /^-{2,}\s*Original Message\s*-{2,}/im,
  /^From:\s.+\n(?:.*\n){0,3}?(?:Sent|Date):\s.+/im,
  /^_{8,}\s*\n\s*From:/im,
];

// A paragraph that is boilerplate, not content.
const FOOTER = [
  /\byou (?:are )?receiv(?:ed|ing) this (?:e-?mail|message|notification)\b/i,
  /\bunsubscribe\b/i,
  /\b(?:update|manage|change) (?:your )?(?:notification|email|subscription) (?:settings|preferences)\b/i,
  /\bnotification preferences\b/i,
  /\bthis (?:e-?mail|message)(?: and any (?:attachments|files))? (?:is|are|may (?:be|contain)) (?:confidential|privileged|intended)/i,
  /\b(?:confidentiality|privileged and confidential|disclaimer)\b/i,
  /\bif you (?:are not|have received this) (?:the intended recipient|in error)\b/i,
  /\bplease consider the environment before printing\b/i,
  /^sent from my (?:iphone|ipad|android|samsung|mobile)/i,
  /^get outlook for (?:ios|android)/i,
  /\bdo not reply to this (?:e-?mail|message)\b|\bthis is an automated (?:e-?mail|message)\b/i,
  /\bprivacy (?:policy|statement|notice)\b/i,
  /\bview (?:it|this e-?mail) in your browser\b/i,
];

// "Best regards," and friends: the signature starts after the name below it.
const SIGN_OFF =
  /^(?:best(?: regards| wishes)?|kind regards|warm(?:est)? regards|regards|thanks(?: and regards| & regards)?|thank you(?: and regards)?|many thanks|cheers|sincerely|yours (?:sincerely|faithfully)|with appreciation)[,!.]?\s*$/i;

function isFooter(paragraph: string): boolean {
  return FOOTER.some((pattern) => pattern.test(paragraph));
}

/** Cut a reply at the first quoted older message. */
function splitQuoted(paragraphs: string[]): { main: string[]; earlier: string[] } {
  for (let index = 0; index < paragraphs.length; index += 1) {
    const paragraph = paragraphs[index];
    for (const pattern of QUOTE_START) {
      const found = pattern.exec(paragraph);
      if (!found) continue;
      const before = paragraph.slice(0, found.index).trim();
      const after = paragraph.slice(found.index).trim();
      const main = paragraphs.slice(0, index);
      if (before) main.push(before);
      return { main, earlier: [after, ...paragraphs.slice(index + 1)] };
    }
    // Lines quoted with ">" (plain-text replies).
    const lines = paragraph.split("\n");
    if (lines.length > 0 && lines.every((line) => line.trim().startsWith(">"))) {
      return { main: paragraphs.slice(0, index), earlier: paragraphs.slice(index) };
    }
  }
  return { main: paragraphs, earlier: [] };
}

/** Keep "Best regards,\nName" but fold the title, phone and address lines after it. */
function splitSignature(main: string[]): { main: string[]; footer: string[] } {
  // Look a few paragraphs back: a signature can span several one-line paragraphs.
  const start = Math.max(0, main.length - 8);
  for (let index = main.length - 1; index >= start; index -= 1) {
    const lines = main[index].split("\n");
    const at = lines.findIndex((line) => SIGN_OFF.test(line.trim()) || line.trim() === "--");
    if (at === -1) continue;
    const dashes = lines[at].trim() === "--";
    let kept: string[];
    let tail: string[];
    if (dashes || at + 1 < lines.length) {
      // The name is on the next line of the same paragraph (or "--" starts the signature).
      const keep = dashes ? at : at + 2;
      kept = [...main.slice(0, index), lines.slice(0, keep).join("\n").trim()].filter(Boolean);
      tail = [lines.slice(keep).join("\n").trim(), ...main.slice(index + 1)].filter(Boolean);
    } else {
      // "Best regards," alone: the name is the next paragraph.
      kept = main.slice(0, index + 2);
      tail = main.slice(index + 2);
    }
    // Only a short tail is a signature; a long one is still the message.
    if (tail.join("\n").length > 600) return { main, footer: [] };
    return { main: kept, footer: tail };
  }
  return { main, footer: [] };
}

/**
 * Tidy the paragraphs: trim each line, and split a body that arrived as one
 * long paragraph (HTML mail without paragraph breaks) into its lines.
 */
function normalise(paragraphs: readonly string[]): string[] {
  const trimmed = paragraphs
    .map((paragraph) =>
      paragraph
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .join("\n"),
    )
    .filter(Boolean);
  const lines = trimmed.reduce((count, paragraph) => count + paragraph.split("\n").length, 0);
  if (trimmed.length <= 2 && lines >= 5) {
    return trimmed.flatMap((paragraph) => paragraph.split("\n"));
  }
  return trimmed;
}

export function cleanBody(paragraphs: readonly string[]): CleanBody {
  const blocks = normalise(paragraphs);
  const { main: beforeQuote, earlier } = splitQuoted(blocks);

  // Boilerplate paragraphs at the end (scan back while they keep matching).
  let end = beforeQuote.length;
  while (end > 0 && isFooter(beforeQuote[end - 1])) end -= 1;
  const trailing = beforeQuote.slice(end);
  // Boilerplate anywhere else is folded too (e.g. a disclaimer above the sign-off).
  const content = beforeQuote.slice(0, end).filter((paragraph) => !isFooter(paragraph));
  const scattered = beforeQuote.slice(0, end).filter(isFooter);

  const { main, footer: signature } = splitSignature(content);
  const result = { main, footer: [...signature, ...scattered, ...trailing], earlier };

  // Never hide everything: an email that is all "boilerplate" shows as it is.
  return result.main.length > 0 ? result : { main: [...paragraphs], footer: [], earlier: [] };
}
