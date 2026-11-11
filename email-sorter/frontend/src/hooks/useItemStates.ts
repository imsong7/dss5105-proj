import { useCallback, useEffect, useState } from "react";

import { fetchItemStates, saveItemState } from "../services/flask";
import type { ItemState } from "../services/flask";


export function useItemStates() {
  const [states, setStates] = useState<Readonly<Record<string, ItemState>>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();

    fetchItemStates(abort.signal)
      .then(setStates)
      .catch(() => {
        // Marks are a convenience; the app works without them.
      });

    return () => abort.abort();
  }, []);

  const update = useCallback(
    async (key: string, next: ItemState | null) => {
      const previous = states[key];

      // Optimistic: the row disappears at once and returns if saving fails.
      setStates((current) => {
        const copy = { ...current };
        if (next && (next.done || next.snoozedUntil)) {
          copy[key] = next;
        } else {
          delete copy[key];
        }
        return copy;
      });
      setError(null);

      try {
        await saveItemState(key, next);
      } catch (cause) {
        setStates((current) => {
          const copy = { ...current };
          if (previous) {
            copy[key] = previous;
          } else {
            delete copy[key];
          }
          return copy;
        });
        setError(cause instanceof Error ? cause.message : "Could not save.");
      }
    },
    [states],
  );

  const setDone = useCallback(
    (key: string, done: boolean) =>
      update(key, done ? { done: true, snoozedUntil: "", at: new Date().toISOString() } : null),
    [update],
  );

  const snooze = useCallback(
    (key: string, until: string) =>
      update(key, until ? { done: false, snoozedUntil: until } : null),
    [update],
  );

  /** Hidden from Today: done, or snoozed to a later day. */
  const isHidden = useCallback(
    (key: string, today: string) => {
      const state = states[key];
      return Boolean(state && (state.done || state.snoozedUntil > today));
    },
    [states],
  );

  const isDone = useCallback((key: string) => states[key]?.done === true, [states]);

  return { states, error, setDone, snooze, isHidden, isDone };
}

export type ItemStates = ReturnType<typeof useItemStates>;
