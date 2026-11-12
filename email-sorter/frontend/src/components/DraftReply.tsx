import { useEffect, useRef, useState } from "react";
import { Copy, Loader2, RefreshCw, Send, Sparkles } from "lucide-react";

import type { InboxEmail, ReplyDraft } from "../domain/email";

interface DraftReplyProps {
  email: InboxEmail;
  onDraft: (id: string, signal?: AbortSignal) => Promise<ReplyDraft>;
  /** Start drafting as soon as the panel opens (it was opened by a "Draft a reply" button). */
  autoStart?: boolean;
}

/**
 * Where "Send" goes: the original email in Outlook on the web (reply there, in its own
 * thread), or, when that link is unknown, Outlook's new-message page already filled in.
 */
function outlookSendUrl(email: InboxEmail, subject: string, reply: string): string {
  if (email.webLink) {
    return email.webLink;
  }
  // encodeURIComponent, not URLSearchParams: Outlook reads "+" literally instead of as a space.
  const query = [
    ["to", email.sender.address],
    ["subject", subject],
    ["body", reply],
  ]
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
    .join("&");
  return `https://outlook.office.com/mail/deeplink/compose?${query}`;
}

const PRIMARY_BUTTON =
  "mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-[10px] bg-accent px-3.5 text-[13px] font-semibold text-white transition-colors hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface focus-visible:outline-none disabled:cursor-wait disabled:opacity-60";
const ACTION_PRIMARY =
  "inline-flex min-h-11 items-center gap-1.5 rounded-[10px] bg-accent px-3.5 text-[13px] font-semibold text-white transition-colors hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface focus-visible:outline-none disabled:cursor-wait disabled:opacity-60";
const SECONDARY_BUTTON =
  "inline-flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line bg-surface px-3.5 text-[13px] font-semibold text-ink transition-colors hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface focus-visible:outline-none disabled:opacity-60";

export function DraftReply({ email, onDraft, autoStart = false }: DraftReplyProps) {
  const [draft, setDraft] = useState<ReplyDraft | null>(null);
  const [loading, setLoading] = useState(autoStart);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [opened, setOpened] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (autoStart) {
      void generate();
    }
    // Only when the panel first opens.
  }, []);

  const subject = email.subject.trim() || "(no subject)";
  const replySubject = subject.toLowerCase().startsWith("re:") ? subject : `Re: ${subject}`;

  async function generate() {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setLoading(true);
    setError(null);
    setCopied(false);
    setOpened(false);

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

  if (!draft && !loading && !error) {
    // Idle: one small button; the full panel opens only once it is used.
    return (
      <div className="mt-2.5">
        <button
          type="button"
          onClick={() => void generate()}
          title="Nothing is sent until you press Send"
          className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-line px-3.5 text-[13px] font-semibold text-accent hover:bg-accent-soft focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          Draft a reply
        </button>
      </div>
    );
  }

  return (
    <section
      aria-label="Draft reply"
      className="mt-3 rounded-[10px] border border-line bg-surface-muted p-3.5"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <div>
          <p className="text-[13px] font-semibold text-ink">Draft reply</p>
          <p className="text-[12px] text-muted">
            {draft
              ? `${draft.model || "Generated"} · review before sending`
              : "Generate a draft reply. Nothing is sent until you press Send."}
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
            onChange={(event) => {
              const reply = event.target.value;
              setDraft((current) => (current ? { ...current, reply } : current));
            }}
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
            {/* Sending happens in Outlook: the draft is copied, then Outlook opens. */}
            <a
              href={outlookSendUrl(email, replySubject, draft.reply)}
              target="_blank"
              rel="noopener noreferrer"
              className={ACTION_PRIMARY}
              onClick={() => {
                void copy();
                setOpened(true);
              }}
              title={
                email.webLink
                  ? "Opens the original email in Outlook; click Reply there and paste the draft"
                  : "Opens a new Outlook email to the sender with this draft filled in"
              }
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              Send
            </a>
          </div>
          {opened ? (
            <p role="status" className="mt-2 text-[12px] leading-5 text-muted">
              {email.webLink
                ? "Outlook opened the original email and the draft is copied: click Reply, paste it (Ctrl/Cmd+V) and send."
                : "Outlook opened a new email with the draft filled in (not in the original thread). Check it and send."}
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
