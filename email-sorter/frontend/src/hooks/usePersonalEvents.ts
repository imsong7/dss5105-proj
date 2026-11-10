import { useCallback, useEffect, useState } from "react";

import type { PersonalEvent, PersonalEventDraft } from "../domain/calendar";
import {
  createPersonalEvent,
  deletePersonalEvent,
  fetchPersonalEvents,
  updatePersonalEvent,
} from "../services/flask";

function byDate(events: readonly PersonalEvent[]): PersonalEvent[] {
  return [...events].sort(
    (a, b) =>
      a.date.localeCompare(b.date) || a.time.localeCompare(b.time),
  );
}

export function usePersonalEvents() {
  const [events, setEvents] = useState<readonly PersonalEvent[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();

    fetchPersonalEvents(abort.signal)
      .then((items) => setEvents(byDate(items)))
      .catch((error: unknown) => {
        if (!abort.signal.aborted) {
          setLoadError(
            error instanceof Error ? error.message : "Could not load your events.",
          );
        }
      });

    return () => abort.abort();
  }, []);

  // These throw on failure so the dialog can show the server's message.
  const save = useCallback(
    async (draft: PersonalEventDraft, id?: string) => {
      const saved = id
        ? await updatePersonalEvent(id, draft)
        : await createPersonalEvent(draft);

      setEvents((current) =>
        byDate([...current.filter((event) => event.id !== saved.id), saved]),
      );
    },
    [],
  );

  const remove = useCallback(async (id: string) => {
    await deletePersonalEvent(id);
    setEvents((current) => current.filter((event) => event.id !== id));
  }, []);

  return { events, loadError, save, remove };
}

export type PersonalEvents = ReturnType<typeof usePersonalEvents>;
