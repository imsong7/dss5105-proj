import type { InboxEmail } from "./email";

/** The same words the sorter uses to know a sender cannot receive a reply (claude/config.yaml). */
const NO_REPLY = /no-?reply|do-?not-?reply/i;

/** Canvas sends its notifications from instructure.com addresses. */
const CANVAS_SENDER = /@(?:[\w-]+\.)*instructure\.com$/i;

/**
 * Only mail we are sure nobody can answer: a job digest, a no-reply sender or a Canvas
 * notification. Everything else keeps its "Draft a reply" button, even newsletters, so
 * a wrongly sorted email never loses it.
 */
export function cannotReply(email: InboxEmail): boolean {
  const address = email.sender.address.trim();
  return Boolean(email.jobs) || NO_REPLY.test(address) || CANVAS_SENDER.test(address);
}
