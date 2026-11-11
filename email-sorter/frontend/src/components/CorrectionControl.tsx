import { useState, type ReactNode } from "react";

import type { InboxEmail } from "../domain/email";
import type { ActionKey, CategoryKey } from "../domain/taxonomy";
import {
  ACTION_KEYS,
  CATEGORY_KEYS,
  CONTENT_CATEGORIES,
  REPLY_NATURE,
} from "../domain/taxonomy";

interface CorrectionControlProps {
  email: InboxEmail;
  onCorrect: (
    id: string,
    category: CategoryKey,
    action: ActionKey,
    rememberSender: boolean,
  ) => Promise<void>;
  onUndo: (id: string) => Promise<void>;
  onRemoveRule: (id: string) => Promise<void>;
  /** Shown before the fix link while not editing, e.g. the "Why?" toggle. */
  extra?: ReactNode;
}

const SELECT =
  "mt-1 h-11 w-full rounded-[10px] border border-line bg-surface px-3 text-[14px] text-ink focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none";

const LINK =
  "inline-flex min-h-11 items-center rounded-lg px-1.5 text-[13px] sm:min-h-8 font-medium text-accent underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:opacity-60";

export function CorrectionControl({
  email,
  onCorrect,
  onUndo,
  onRemoveRule,
  extra,
}: CorrectionControlProps) {
  const current = email.classification;
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState<CategoryKey>(current?.category ?? "others");
  const [action, setAction] = useState<ActionKey>(current?.action ?? "no_immediate_action");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!current) {
    return null;
  }

  async function run(task: () => Promise<void>, done?: () => void) {
    setBusy(true);
    setError(null);

    try {
      await task();
      done?.();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <div className="ml-auto flex flex-wrap items-center gap-x-1">
        {current.byRule ? (
          <>
            <span className="text-[13px] text-muted">Your rule for this sender</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => onRemoveRule(email.id))}
              className={LINK}
            >
              Remove rule
            </button>
          </>
        ) : null}
        {current.corrected ? (
          <>
            <span className="text-[13px] text-muted">Edited by you</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => onUndo(email.id))}
              className={LINK}
            >
              Undo
            </button>
          </>
        ) : null}
        {extra}
        <button
          type="button"
          onClick={() => {
            setCategory(current.category);
            setAction(current.action);
            setRemember(false);
            setError(null);
            setEditing(true);
          }}
          className={LINK}
        >
          {current.corrected ? "Change again" : "Fix label"}
        </button>
        {error ? (
          <span role="alert" className="text-[13px] text-action-now-fg">
            {error}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <form
      className="mt-2 w-full basis-full rounded-[10px] border border-line bg-surface p-3.5"
      onSubmit={(event) => {
        event.preventDefault();
        void run(
          () => onCorrect(email.id, category, action, remember),
          () => setEditing(false),
        );
      }}
    >
      <p className="text-[13px] font-semibold text-ink">Fix the labels</p>
      <p className="mt-0.5 text-[13px] text-muted">
        Your fix is remembered and helps measure how well the sorter works.
      </p>
      <div className="mt-2.5 grid gap-3 sm:grid-cols-2">
        <label className="text-[13px] font-medium text-muted">
          What to do
          <select
            value={action}
            onChange={(event) => setAction(event.target.value as ActionKey)}
            className={SELECT}
          >
            {ACTION_KEYS.map((key) => (
              <option key={key} value={key}>
                {REPLY_NATURE[key]}
              </option>
            ))}
          </select>
        </label>
        <label className="text-[13px] font-medium text-muted">
          Category
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value as CategoryKey)}
            className={SELECT}
          >
            {CATEGORY_KEYS.map((key) => (
              <option key={key} value={key}>
                {CONTENT_CATEGORIES[key]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {email.sender.address ? (
        <label className="mt-3 flex min-h-11 items-center gap-2.5 text-[13px] text-ink">
          <input
            type="checkbox"
            checked={remember}
            onChange={(event) => setRemember(event.target.checked)}
            className="h-4.5 w-4.5 accent-accent"
          />
          <span className="min-w-0">
            Always do this for <strong className="font-semibold">{email.sender.name}</strong>
          </span>
        </label>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-[13px] text-action-now-fg">
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={() => setEditing(false)}
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
    </form>
  );
}
