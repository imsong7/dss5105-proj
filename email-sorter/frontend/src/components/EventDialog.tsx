import { useEffect, useRef, useState } from "react";

import type { PersonalEvent, PersonalEventDraft } from "../domain/calendar";

export type EventDialogTarget =
  | { mode: "new"; date: string }
  | { mode: "edit"; event: PersonalEvent }
  | null;

interface EventDialogProps {
  target: EventDialogTarget;
  onSave: (draft: PersonalEventDraft, id?: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onClose: () => void;
}

const INPUT =
  "mt-1.5 h-11 w-full rounded-[10px] border border-line bg-surface px-3 text-[14px] text-ink focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none";

export function EventDialog({ target, onSave, onDelete, onClose }: EventDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) {
      return;
    }

    if (target) {
      const event = target.mode === "edit" ? target.event : null;
      setTitle(event?.title ?? "");
      setDate(event?.date ?? (target.mode === "new" ? target.date : ""));
      setTime(event?.time ?? "");
      setNotes(event?.notes ?? "");
      setError(null);
      setBusy(false);
      if (!dialog.open) {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [target]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);

    try {
      await action();
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Something went wrong.");
      setBusy(false);
    }
  }

  const editing = target?.mode === "edit" ? target.event : null;

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="event-dialog-title"
      className="m-auto w-[min(440px,calc(100%-32px))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-[0_24px_60px_rgba(0,0,0,0.25)] backdrop:bg-black/40"
    >
      <form
        method="dialog"
        className="p-5"
        onSubmit={(event) => {
          event.preventDefault();
          void run(() => onSave({ title, date, time, notes }, editing?.id));
        }}
      >
        <h2 id="event-dialog-title" className="text-[17px] font-semibold">
          {editing ? "Edit event" : "Add event"}
        </h2>

        <label htmlFor="event-title" className="mt-4 block text-[13px] font-medium">
          Title
        </label>
        <input
          id="event-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={120}
          required
          autoComplete="off"
          placeholder="e.g. Group meeting, Study for quiz"
          className={INPUT}
        />

        <div className="mt-3 grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="event-date" className="block text-[13px] font-medium">
              Date
            </label>
            <input
              id="event-date"
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              required
              className={INPUT}
            />
          </div>
          <div>
            <label htmlFor="event-time" className="block text-[13px] font-medium">
              Time <span className="font-normal text-muted">(optional)</span>
            </label>
            <input
              id="event-time"
              type="time"
              value={time}
              onChange={(event) => setTime(event.target.value)}
              className={INPUT}
            />
          </div>
        </div>

        <label htmlFor="event-notes" className="mt-3 block text-[13px] font-medium">
          Notes <span className="font-normal text-muted">(optional)</span>
        </label>
        <textarea
          id="event-notes"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          maxLength={500}
          className="mt-1.5 min-h-20 w-full rounded-[10px] border border-line bg-surface p-3 text-[14px] text-ink focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
        />

        {error ? (
          <p role="alert" className="mt-2 text-[13px] text-action-now-fg">
            {error}
          </p>
        ) : null}

        <div className="mt-4 flex items-center gap-2">
          {editing ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => onDelete(editing.id))}
              className="min-h-11 rounded-[10px] px-3 text-[14px] font-medium text-action-now-fg hover:bg-action-now-bg focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:opacity-60"
            >
              Delete
            </button>
          ) : null}
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="min-h-11 rounded-[10px] px-4 text-[14px] font-medium text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="min-h-11 rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
            >
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </form>
    </dialog>
  );
}
