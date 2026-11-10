import type { CalendarDeadline } from "./calendar";
import { addDays } from "./calendar";
import type { InboxEmail } from "./email";

export interface TodaySections {
  overdue: CalendarDeadline[];
  today: CalendarDeadline[];
  soon: CalendarDeadline[];
  reply: InboxEmail[];
  action: InboxEmail[];
}

const OVERDUE_DAYS = 14;
const SOON_DAYS = 7;
const LIST_LIMIT = 8;

/**
 * What the student should look at now. Deadlines come from the calendar items
 * (so they already include course colors and personal events). Mail that is
 * already listed under a deadline is not repeated under "reply" or "action".
 */
/** Key for done/snooze marks: an email id, or ``event:<id>`` for your own events. */
export function itemKey(item: CalendarDeadline): string {
  return item.personal ? `event:${item.personal.id}` : (item.stateKey ?? item.emailId);
}

export function buildToday(
  deadlines: readonly CalendarDeadline[],
  emails: readonly InboxEmail[],
  today: string,
  hidden: (key: string) => boolean = () => false,
): TodaySections {
  const oldest = addDays(today, -OVERDUE_DAYS);
  const latest = addDays(today, SOON_DAYS);

  const shown = deadlines.filter((item) => !hidden(itemKey(item)));
  const overdue = shown.filter(
    (item) => !item.personal && item.date < today && item.date >= oldest,
  );
  const dueToday = shown.filter((item) => item.date === today);
  const soon = shown.filter((item) => item.date > today && item.date <= latest);

  const listed = new Set(
    [...overdue, ...dueToday, ...soon]
      .map((item) => item.emailId)
      .filter(Boolean),
  );

  const newestFirst = (a: InboxEmail, b: InboxEmail) =>
    Date.parse(b.receivedAt) - Date.parse(a.receivedAt);

  const open = emails.filter(
    (email) =>
      !listed.has(email.id) && email.classification && !hidden(email.id),
  );

  return {
    overdue: overdue.sort((a, b) => b.date.localeCompare(a.date)),
    today: dueToday,
    soon,
    reply: open
      .filter((email) => email.classification?.action === "needs_reply")
      .sort(newestFirst)
      .slice(0, LIST_LIMIT),
    action: open
      .filter((email) => email.classification?.action === "needs_action")
      .sort(newestFirst)
      .slice(0, LIST_LIMIT),
  };
}

export function countToday(sections: TodaySections): number {
  return (
    sections.overdue.length +
    sections.today.length +
    sections.soon.length +
    sections.reply.length +
    sections.action.length
  );
}

export function isEmptyToday(sections: TodaySections): boolean {
  return countToday(sections) === 0;
}
