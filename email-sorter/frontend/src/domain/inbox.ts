import type {
  InboxEmail,
  DateRange,
  InboxFilters,
  SortOrder,
  WindowDays,
} from "./email";
import type { ActionKey, CategoryKey } from "./taxonomy";
import { ACTION_KEYS } from "./taxonomy";

/** Counts are computed over the full inbox, independent of active filters. */
export function countByAction(
  emails: readonly InboxEmail[],
): Record<ActionKey, number> {
  const counts = Object.fromEntries(
    ACTION_KEYS.map((key) => [key, 0]),
  ) as Record<ActionKey, number>;

  for (const email of emails) {
    if (email.classification) {
      counts[email.classification.action] += 1;
    }
  }

  return counts;
}

/** Search covers sender name, sender address, subject and the start of the body. */
export function filterEmails(
  emails: readonly InboxEmail[],
  filters: InboxFilters,
): InboxEmail[] {
  const query = filters.query.trim().toLowerCase();
  const categories = new Set<CategoryKey>(filters.categories);

  return emails.filter((email) => {
    const haystack =
      `${email.sender.name} ${email.sender.address} ${email.subject} ${email.body.slice(0, 5000)}`.toLowerCase();

    return (
      (!query || haystack.includes(query)) &&
      (filters.action === "all" ||
        email.classification?.action === filters.action) &&
      (categories.size === 0 ||
        (email.classification !== undefined &&
          categories.has(email.classification.category)))
    );
  });
}

/** Stable sort: ties fall back to the id so screenshots are deterministic. */
export function sortEmails(
  emails: readonly InboxEmail[],
  order: SortOrder,
): InboxEmail[] {
  return [...emails].sort((a, b) => {
    const delta = Date.parse(a.receivedAt) - Date.parse(b.receivedAt);
    const ordered = order === "oldest" ? delta : -delta;
    return ordered !== 0 ? ordered : a.id.localeCompare(b.id);
  });
}

/** Keep emails received within the last `days` days. 0 keeps everything. */
export function withinWindow(
  emails: readonly InboxEmail[],
  days: WindowDays,
  range: DateRange = { since: "", before: "" },
  now: number = Date.now(),
): InboxEmail[] {
  if (days === 0) {
    return [...emails];
  }

  if (days === "custom") {
    const start = range.since ? Date.parse(`${range.since}T00:00:00`) : -Infinity;
    const end = range.before ? Date.parse(`${range.before}T23:59:59.999`) : Infinity;

    return emails.filter((email) => {
      const time = Date.parse(email.receivedAt);
      return Number.isNaN(time) || (time >= start && time <= end);
    });
  }

  const cutoff = now - days * 86_400_000;

  return emails.filter((email) => {
    const time = Date.parse(email.receivedAt);
    return Number.isNaN(time) || time >= cutoff;
  });
}

const HONORIFICS = new Set(["dr.", "prof.", "mr.", "mrs.", "ms.", "mx."]);

export function senderInitials(name: string): string {
  const words = name
    .split(/\s+/)
    .filter((word) => word.length > 0 && !HONORIFICS.has(word.toLowerCase()));

  const letters = words
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");

  return letters || "?";
}
