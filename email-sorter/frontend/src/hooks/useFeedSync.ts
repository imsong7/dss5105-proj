import { useEffect } from "react";

import type { CalendarDeadline } from "../domain/calendar";
import { addDays, todayKey } from "../domain/calendar";
import { syncFeed } from "../services/flask";
import type { FeedItem } from "../services/flask";

/**
 * Keeps the server's calendar feed in step with the deadlines on screen. Your
 * own events are not sent: the server already has them.
 */
export function useFeedSync(
  deadlines: readonly CalendarDeadline[],
  isDone: (key: string) => boolean,
  ready: boolean,
) {
  useEffect(() => {
    if (!ready) {
      return;
    }

    const cutoff = addDays(todayKey(), -30);
    const items: FeedItem[] = deadlines
      .filter((item) => !item.personal && item.emailId && item.date >= cutoff && !isDone(item.stateKey ?? item.emailId))
      .map((item) => ({
        key: item.stateKey ?? item.emailId,
        title: item.course ? `${item.course} · ${item.subject}` : item.subject,
        date: item.date,
        time: item.time ?? "",
        detail: item.sender,
        url: item.link?.url ?? "",
      }));

    // Wait a moment so a burst of changes becomes one request.
    const timer = window.setTimeout(() => {
      void syncFeed(items).catch(() => {
        // The feed is a convenience; try again on the next change.
      });
    }, 1500);

    return () => window.clearTimeout(timer);
  }, [deadlines, isDone, ready]);
}
