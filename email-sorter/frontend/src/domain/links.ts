import type { InboxEmail } from "./email";

export interface EmailLink {
  url: string;
  /** Short button text such as "Open in Canvas". */
  label: string;
  /** Higher is more likely to be the link a student wants. */
  score: number;
}

const URL_PATTERN = /https?:\/\/[^\s<>"')\]]+/gi;
const IGNORED =
  /unsubscribe|optout|opt-out|preferences|tracking|pixel|click\.|\/track|safelinks|\.(png|jpe?g|gif|svg|webp)(\?|$)/i;

function classify(url: URL): { label: string; score: number } {
  const host = url.hostname.toLowerCase();
  const full = `${host}${url.pathname}`.toLowerCase();

  if (/instructure\.com$|canvas\./.test(host)) return { label: "Open in Canvas", score: 5 };
  if (host.endsWith("kaggle.com")) return { label: "Open Kaggle", score: 4 };
  if (
    /(^|\.)forms\.(gle|office\.com)$/.test(host) ||
    full.includes("docs.google.com/forms") ||
    host.endsWith("typeform.com")
  ) {
    return { label: "Open form", score: 4 };
  }
  if (host.endsWith("zoom.us")) return { label: "Join Zoom", score: 3 };
  if (host === "teams.microsoft.com" || host === "meet.google.com") {
    return { label: "Join meeting", score: 3 };
  }
  return { label: "Open link", score: 1 };
}

/** Button text for one link, e.g. "Open form" or "Join Zoom". */
export function linkLabel(url: string): string {
  try {
    return classify(new URL(url)).label;
  } catch {
    return "Open link";
  }
}

/** Every usable http(s) link in the email, best first, without duplicates. */
export function emailLinks(email: Pick<InboxEmail, "body" | "preview">): EmailLink[] {
  const text = `${email.body}\n${email.preview}`;
  const seen = new Set<string>();
  const links: EmailLink[] = [];

  for (const match of text.matchAll(URL_PATTERN)) {
    const cleaned = match[0].replace(/[.,;:!?]+$/, "");

    if (cleaned.length > 400 || IGNORED.test(cleaned) || seen.has(cleaned)) {
      continue;
    }

    let parsed: URL;
    try {
      parsed = new URL(cleaned);
    } catch {
      continue;
    }

    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      continue;
    }

    seen.add(cleaned);
    links.push({ url: cleaned, ...classify(parsed) });
  }

  // Stable sort keeps the email's own order among equally likely links.
  return links
    .map((link, index) => ({ link, index }))
    .sort((a, b) => b.link.score - a.link.score || a.index - b.index)
    .map(({ link }) => link);
}

export function bestLink(email: Pick<InboxEmail, "body" | "preview">): EmailLink | undefined {
  return emailLinks(email)[0];
}
