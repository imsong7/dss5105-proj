import type { RefObject } from "react";
import { ArrowLeft, CalendarClock, ExternalLink, Mail } from "lucide-react";

import type { InboxEmail, ReplyDraft } from "../domain/email";
import type { ActionKey, CategoryKey } from "../domain/taxonomy";
import { senderInitials } from "../domain/inbox";
import { formatDeadline, formatFullDate } from "../lib/format";
import { CategoryBadge } from "./CategoryBadge";
import { emailLinks } from "../domain/links";
import { CorrectionControl } from "./CorrectionControl";
import { DraftReply } from "./DraftReply";
import { JobsCard } from "./JobsCard";
import { PosterCard } from "./PosterCard";
import { StatusBadge } from "./StatusBadge";

interface EmailDetailProps {
  email: InboxEmail | null;
  onBack: () => void;
  /** Text of the Back button on phones. */
  backLabel?: string;
  onCorrect: (
    id: string,
    category: CategoryKey,
    action: ActionKey,
    rememberSender: boolean,
  ) => Promise<void>;
  onUndoCorrection: (id: string) => Promise<void>;
  onRemoveRule: (id: string) => Promise<void>;
  onDraftReply: (id: string, signal?: AbortSignal) => Promise<ReplyDraft>;
  onSendReply: (id: string, reply: string, token?: string) => Promise<void>;
  headingRef: RefObject<HTMLHeadingElement | null>;
  className?: string;
}

export function EmailDetail({
  email,
  onBack,
  backLabel = "Back to inbox",
  onCorrect,
  onUndoCorrection,
  onRemoveRule,
  onDraftReply,
  onSendReply,
  headingRef,
  className = "",
}: EmailDetailProps) {
  if (!email) {
    return (
      <section
        aria-label="Email details"
        className={`min-w-0 flex-1 flex-col lg:overflow-y-auto inbox-scroll ${className}`}
      >
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
          <span
            className="grid h-12 w-12 place-items-center rounded-full bg-surface-muted text-muted"
            aria-hidden="true"
          >
            <Mail className="h-5 w-5" />
          </span>
          <p className="text-[14px] font-semibold text-ink">Select an email</p>
          <p className="max-w-[36ch] text-[14px] leading-5 text-muted">
            Pick a message from the list to see its contents, classification
            reason, and any deadline found in the text.
          </p>
        </div>
      </section>
    );
  }

  const { sender, subject, body, receivedAt, classification, deadline } = email;
  // Every date found, shown in one card; tap a date to see where it came from.
  const dates = email.deadlines?.length ? email.deadlines : deadline ? [deadline] : [];
  const links = emailLinks(email);

  // Blank lines are paragraph breaks in the synthetic copy; render them as
  // real paragraphs so spacing stays tight and consistent.
  // Text read from images is part of `body` (for sorting) but is shown folded
  // away below; the poster card above already carries what matters in it.
  const ocrText = email.ocrText ?? "";
  const bodyText =
    ocrText && body.endsWith(ocrText) ? body.slice(0, body.length - ocrText.length).trim() : body;
  const bodyParagraphs = bodyText
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  return (
    <section
      aria-label="Email details"
      className={`min-w-0 flex-1 flex-col lg:overflow-y-auto inbox-scroll ${className}`}
    >
      <div className="border-b border-line px-3 py-2 lg:hidden">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium text-accent transition-colors hover:bg-accent-soft focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {backLabel}
        </button>
      </div>

      <article className="flex min-w-0 max-w-[720px] flex-1 flex-col p-5 sm:p-7">
        <div className="flex items-start gap-3">
          <span
            className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-surface-muted text-[14px] font-semibold text-ink/60"
            aria-hidden="true"
          >
            {senderInitials(sender.name)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-semibold text-ink">
              {sender.name}
            </p>
            <p className="truncate text-[13px] text-muted">
              {sender.address}
            </p>
          </div>
          <time
            className="hidden shrink-0 pt-0.5 text-[13px] text-muted sm:block"
            dateTime={receivedAt}
          >
            {formatFullDate(receivedAt)}
          </time>
        </div>

        <p className="mt-2 text-[13px] text-muted sm:hidden">
          {formatFullDate(receivedAt)}
        </p>

        <h2
          id="email-detail-heading"
          ref={headingRef}
          tabIndex={-1}
          className="mt-4 text-xl leading-snug font-semibold tracking-tight text-ink focus:outline-none sm:text-2xl"
        >
          {subject}
        </h2>

        {dates.length > 0 ? (
          <div className="mt-4 flex items-start gap-3 rounded-[10px] border border-highlight-line bg-highlight-soft px-3.5 py-3">
            <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-highlight-dark" aria-hidden="true" />
            <ul className="flex min-w-0 flex-1 flex-col gap-2">
              {dates.map((item, index) => (
                <li key={`${item.date}-${index}`}>
                  <details className="group">
                    <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2 text-[14px] [&::-webkit-details-marker]:hidden">
                      <span className="font-semibold text-ink">{item.label}</span>
                      <span className="text-ink">{formatDeadline(item)}</span>
                      {item.fromImage ? (
                        <span className="text-[12px] text-muted">· from the poster</span>
                      ) : null}
                      {item.yearInferred ? (
                        <span className="text-[12px] font-medium text-highlight-dark">· please check</span>
                      ) : null}
                    </summary>
                    <p className="mt-1 text-[12px] text-muted">
                      {item.yearInferred ? "Worked out from the day this was sent. " : ""}
                      {item.evidence ? `Found in: “${item.evidence}”` : ""}
                    </p>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <PosterCard email={email} />
        {email.jobs ? <JobsCard jobs={email.jobs.items} moreUrl={email.jobs.moreUrl} /> : null}

        {links.length > 0 && !email.jobs ? (
          <div className="mt-3">
            <a
              href={links[0].url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line bg-surface px-3.5 text-[14px] font-semibold text-accent hover:bg-accent-soft focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              {links[0].label}
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            </a>
            {links.length > 1 ? (
              <details className="mt-1">
                <summary className="inline-flex min-h-11 cursor-pointer items-center text-[13px] text-muted hover:text-ink">
                  {links.length - 1} more link{links.length === 2 ? "" : "s"}
                </summary>
                <ul className="flex flex-col gap-1 pb-1">
                  {links.slice(1, 8).map((link) => (
                    <li key={link.url} className="min-w-0">
                      <a
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block truncate text-[13px] text-accent underline-offset-2 hover:underline"
                      >
                        {link.label}: {link.url}
                      </a>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}

        {classification ? (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <CategoryBadge category={classification.category} size="md" />
              <StatusBadge action={classification.action} size="md" />
            </div>

            <CorrectionControl
              key={email.id}
              email={email}
              onCorrect={onCorrect}
              onUndo={onUndoCorrection}
              onRemoveRule={onRemoveRule}
            />

            {classification.reason ? (
              <details className="mt-1">
                <summary className="inline-flex min-h-11 cursor-pointer items-center text-[13px] text-muted hover:text-ink">
                  Why this label?
                </summary>
                <p className="text-[14px] leading-6 text-ink/85">{classification.reason}</p>
              </details>
            ) : null}
          </>
        ) : (
          <p
            className={`mt-3 text-[13px] ${email.classifyError ? "text-action-now-fg" : "text-muted"}`}
          >
            {email.classifyError
              ? `Could not classify: ${email.classifyError}`
              : "Not sorted yet. It is sorted with the next batch, or press Sort to do it now."}
          </p>
        )}

        <DraftReply
          key={email.id}
          email={email}
          onDraft={onDraftReply}
          onSend={onSendReply}
        />

        {bodyParagraphs.length > 0 && email.jobs ? (
          // The job list above is the useful part; the flattened digest text folds away.
          <details className="mt-4 rounded-xl border border-line px-3.5 py-2">
            <summary className="flex min-h-9 cursor-pointer items-center text-[13px] text-muted hover:text-ink">
              Show the original email
            </summary>
            <div className="space-y-3 pb-2 text-[13px] leading-5 break-words text-ink/80">
              {bodyParagraphs.map((paragraph, index) => (
                <p key={index} className="whitespace-pre-wrap">
                  <LinkedText text={paragraph} />
                </p>
              ))}
            </div>
          </details>
        ) : bodyParagraphs.length > 0 ? (
          <div className="mt-6 border-t border-line pt-5 text-[15px] leading-6 break-words text-ink/90 space-y-3 sm:text-[16px]">
            {bodyParagraphs.map((paragraph, index) => (
              <p key={index} className="whitespace-pre-wrap">
                <LinkedText text={paragraph} />
              </p>
            ))}
          </div>
        ) : null}

        {ocrText ? (
          <details className="mt-4 rounded-xl border border-line px-3.5 py-2">
            <summary className="flex min-h-9 cursor-pointer items-center text-[13px] text-muted hover:text-ink">
              Show text read from the image
            </summary>
            <p className="mt-1 pb-2 text-[13px] leading-5 whitespace-pre-wrap text-ink/80">
              {ocrText.replace(/^\[Text read from image[^\]]*\]\n?/gm, "").trim()}
            </p>
          </details>
        ) : null}

      </article>
    </section>
  );
}

/**
 * Body text where "label<https://...>" (how links arrive) shows the label with
 * a small link icon instead of the long address.
 */
function LinkedText({ text }: { text: string }) {
  const parts = text.split(/<(https?:\/\/[^>\s]+)>/g);
  if (parts.length === 1) {
    return <>{text}</>;
  }
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <a
            key={index}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            title={part}
            aria-label="Open link"
            className="mx-0.5 inline-flex translate-y-[1px] items-center text-accent hover:text-accent-dark"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}
