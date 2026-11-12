import { useEffect, useRef, useState } from "react";

import type { PersonalEventDraft } from "../domain/calendar";
import { isCanvasAssignment } from "../domain/course";
import type { InboxEmail } from "../domain/email";
import { scanEmailForEvent } from "../services/flask";
import type { FlaskEmail } from "../services/flask";

const PARALLEL = 3;

/**
 * Claude reads each loaded email once in the background and remembers an event or
 * deadline it finds. The server keeps the answers, so a reload asks nothing new.
 * Canvas assignments and job digests are skipped: they are handled elsewhere.
 */
export function useEmailEvents(
  emails: readonly InboxEmail[],
  rawEmail: (id: string) => FlaskEmail | undefined,
) {
  const [found, setFound] = useState<Readonly<Record<string, PersonalEventDraft>>>({});
  const asked = useRef(new Set<string>());
  const stopped = useRef(false);
  const running = useRef(0);

  const pending = emails
    .filter((email) => !email.jobs && !isCanvasAssignment(email))
    .map((email) => email.id)
    .join("\n");

  useEffect(() => {
    const abort = new AbortController();

    async function pump() {
      while (!stopped.current && !abort.signal.aborted && running.current < PARALLEL) {
        const id = pending.split("\n").find((candidate) => candidate && !asked.current.has(candidate));
        const source = id ? rawEmail(id) : undefined;
        if (!id) {
          return;
        }
        asked.current.add(id);
        if (!source) {
          continue;
        }
        running.current += 1;
        void scanEmailForEvent(source, abort.signal)
          .then((event) => {
            if (event) {
              setFound((current) => ({ ...current, [id]: event }));
            }
          })
          .catch(() => {
            // No key or no network: stop for now instead of failing on every email.
            asked.current.delete(id);
            stopped.current = true;
          })
          .finally(() => {
            running.current -= 1;
            void pump();
          });
      }
    }

    void pump();
    return () => abort.abort();
  }, [pending, rawEmail]);

  return found;
}
