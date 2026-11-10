import { useEffect, useRef, useState } from "react";
import { Copy, Loader2, RefreshCw, Sparkles } from "lucide-react";

import type { InboxEmail, ReplyDraft } from "../domain/email";

interface DraftReplyProps {
  email: InboxEmail;
  onDraft: (id: string, signal?: AbortSignal) => Promise<ReplyDraft>;
}

const PRIMARY_BUTTON =
  "mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-[10px] bg-accent px-3.5 text-[13px] font-semibold text-white transition-colors hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface focus-visible:outline-none disabled:cursor-wait disabled:opacity-60";
const SECONDARY_BUTTON =
  "inline-flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line bg-surface px-3.5 text-[13px] font-semibold text-ink transition-colors hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface focus-visible:outline-none disabled:opacity-60";

export function DraftReply({ email, onDraft }: DraftReplyProps) {
  const [draft, setDraft] = useState<ReplyDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  async function generate() {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setLoading(true);
    setError(null);
    setCopied(false);

    try {
      const result = await onDraft(email.id, controller.signal);
      setDraft(result);
    } catch (cause) {
      if (controller.signal.aborted) {
        return;
      }
      setError(cause instanceof Error ? cause.message : "Could not draft a reply.");
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }

  async function copy() {
    if (!draft) {
      return;
    }
    try {
      await navigator.clipboard.writeText(draft.reply);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy. Select the text and copy it manually.");
    }
  }

  return (
    <section
      aria-label="Draft reply"
      className="mt-4 rounded-[10px] border border-line bg-surface-muted p-3.5"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <div>
          <p className="text-[13px] font-semibold text-ink">Draft reply</p>
          <p className="text-[12px] text-muted">
            {draft
              ? `${draft.model || "Generated"} · nothing is sent`
              : "Generate a draft reply. Nothing is sent."}
          </p>
        </div>
      </div>

      {!draft && !loading && !error ? (
        <button type="button" className={PRIMARY_BUTTON} onClick={() => void generate()}>
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          Draft reply
        </button>
      ) : null}

      {loading ? (
        <p role="status" className="mt-3 inline-flex items-center gap-2 text-[13px] text-muted">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Drafting a reply...
        </p>
      ) : null}

      {error ? (
        <div className="mt-3 rounded-[8px] border border-action-now-line bg-action-now-bg px-3 py-2">
          <p role="alert" className="text-[13px] leading-5 text-action-now-fg">
            {error}
          </p>
          <button type="button" className={SECONDARY_BUTTON} onClick={() => void generate()}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Try again
          </button>
        </div>
      ) : null}

      {draft ? (
        <>
          <textarea
            aria-label="Draft reply text"
            className="mt-3 w-full resize-y rounded-[10px] border border-line bg-surface px-3.5 py-3 text-[14px] leading-6 text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            rows={Math.min(14, Math.max(7, draft.reply.split("\n").length + 1))}
            value={draft.reply}
            onChange={(event) =>
              setDraft((current) => (current ? { ...current, reply: event.target.value } : current))
            }
          />

          {draft.placeholders.length ? (
            <p className="mt-2 text-[12px] leading-5 text-muted">
              Placeholders:{" "}
              <span className="font-medium text-ink">{draft.placeholders.join(", ")}</span>
            </p>
          ) : null}

          {draft.guardrailIssues.length ? (
            <div className="mt-2 rounded-[8px] border border-highlight-line bg-highlight-soft px-3 py-2">
              <p className="text-[12px] font-semibold text-highlight-dark">Check before sending</p>
              <ul className="mt-1 space-y-1 text-[12px] leading-5 text-highlight-dark">
                {draft.guardrailIssues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className={SECONDARY_BUTTON}
              onClick={() => void generate()}
              disabled={loading}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Regenerate
            </button>
            <button type="button" className={SECONDARY_BUTTON} onClick={() => void copy()}>
              <Copy className="h-4 w-4" aria-hidden="true" />
              {copied ? "Copied" : "Copy draft"}
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
