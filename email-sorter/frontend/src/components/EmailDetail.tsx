import { useId, useState, type ComponentProps, type RefObject } from "react";
import { ArrowLeft, CalendarCheck, CalendarClock, CalendarPlus, ExternalLink, Mail, Sparkles } from "lucide-react";

import { addsItself, deadlineKey } from "../domain/calendar";
import type { InboxEmail, ReplyDraft } from "../domain/email";
import type { ActionKey, CategoryKey } from "../domain/taxonomy";
import { senderInitials } from "../domain/inbox";
import { formatDeadline, formatFullDate } from "../lib/format";
import { CategoryBadge } from "./CategoryBadge";
import { explainPriority } from "../domain/priority";
import { cannotReply } from "../domain/reply";
import { PriorityEditor } from "./PriorityStars";
import { cleanBody } from "../domain/cleanBody";
import { keyFacts } from "../domain/keyFacts";
import { labelValue, markWhen, toBlocks } from "../domain/readable";
import type { Block } from "../domain/readable";
import { emailLinks } from "../domain/links";
import { CorrectionControl } from "./CorrectionControl";
import { DraftReply } from "./DraftReply";
import { FactsStrip } from "./FactsStrip";
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
  /** Set the stars by hand, or null to go back to the model's rating. */
  onSetPriority: (id: string, stars: number | null) => Promise<void>;
  onDraftReply: (id: string, signal?: AbortSignal) => Promise<ReplyDraft>;
  headingRef: RefObject<HTMLHeadingElement | null>;
  /** Is this date (item key) in the student's calendar? Canvas due dates always are. */
  isInCalendar?: (key: string) => boolean;
  onToggleCalendar?: (key: string, inCalendar: boolean) => void;
  className?: string;
}

export function EmailDetail({
  email,
  onBack,
  backLabel = "Back to inbox",
  onCorrect,
  onUndoCorrection,
  onRemoveRule,
  onSetPriority,
  onDraftReply,
  headingRef,
  isInCalendar,
  onToggleCalendar,
  className = "",
}: EmailDetailProps) {
  // Which email's draft panel is open (it closes when another email is opened).
  const [draftFor, setDraftFor] = useState<string | null>(null);
  if (!email) {
    return (
      <section
        aria-label="Email details"
        className={`min-w-0 flex-1 flex-col lg:overflow-y-auto inbox-scroll ${className}`}
      >
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
          <Mail className="h-6 w-6 text-muted/70" aria-hidden="true" strokeWidth={1.5} />
          <p className="text-[14px] leading-5 font-semibold text-ink">Nothing open yet</p>
          <p className="max-w-[36ch] text-[14px] leading-6 text-muted">
            Pick a message from the list to see its contents, classification
            reason, and any deadline found in the text.
          </p>
        </div>
      </section>
    );
  }

  const { sender, subject, body, receivedAt, classification, deadline } = email;
  // The date found in the email; tap it to see where it came from.
  const found = email.deadlines?.length ? email.deadlines : deadline ? [deadline] : [];
  // Canvas assignments are put in the calendar by themselves, so their date needs no row here.
  // One card is enough: the first date found (the one the Inbox row shows).
  const dates = found.every((item) => addsItself(email, item)) ? [] : found.slice(0, 1);

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
  // The message without signature, footer and quoted history (for the facts strip).
  const readableText = cleanBody(bodyParagraphs).main.join("\n");
  // Posters and job digests have their own cards with these facts.
  const facts = email.poster || email.jobs ? [] : keyFacts(subject, readableText);
  // Job digests, no-reply senders and Canvas notifications cannot be answered (see
  // domain/reply.ts). The button sits beside the email's link button ("Open link");
  // pressing it drafts and opens the panel just below.
  const canReply = !cannotReply(email);
  const draftOpen = draftFor === email.id;
  const replyButton =
    canReply && !draftOpen ? (
      <button
        type="button"
        onClick={() => setDraftFor(email.id)}
        className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-line px-3 text-[13px] font-semibold text-accent hover:bg-accent-soft focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
      >
        <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
        Draft a reply
      </button>
    ) : null;
  const actions = replyButton;
  const showFacts = !(email.jobs || (email.event && !email.poster));
  // A meeting link already sits in the facts strip as "Join Zoom".
  const meeting = facts.find((fact) => fact.kind === "meeting")?.href;
  const links = emailLinks(email).filter((link) => link.url !== meeting);

  return (
    <section
      aria-label="Email details"
      className={`min-w-0 flex-1 flex-col lg:overflow-y-auto inbox-scroll ${className}`}
    >
      <div className="border-b border-line px-3 py-2 lg:hidden">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[13px] font-medium text-accent transition-colors hover:bg-accent-soft focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {backLabel}
        </button>
      </div>

      <article className="mx-auto flex w-full min-w-0 max-w-[720px] flex-1 flex-col px-5 py-4 sm:px-7 sm:py-4 lg:px-8 lg:py-4">
        <div className="flex items-start gap-3">
          <span
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-muted text-[12px] font-semibold text-ink/60"
            aria-hidden="true"
          >
            {senderInitials(sender.name)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[14px] leading-5 font-semibold text-ink">
              {sender.name}
            </p>
            <p className="truncate text-[12px] leading-4 text-muted">
              {sender.address}
            </p>
          </div>
          <time
            className="hidden shrink-0 text-[12px] leading-5 text-muted sm:block"
            dateTime={receivedAt}
          >
            {formatFullDate(receivedAt)}
          </time>
          {email.webLink ? (
            <a
              href={email.webLink}
              target="_blank"
              rel="noopener noreferrer"
              title="Open in Outlook"
              aria-label="Open in Outlook"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted hover:bg-accent-soft hover:text-accent focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
            </a>
          ) : null}
        </div>

        <p className="mt-1.5 text-[12px] text-muted sm:hidden">
          {formatFullDate(receivedAt)}
        </p>

        <h2
          id="email-detail-heading"
          ref={headingRef}
          tabIndex={-1}
          className="mt-2.5 text-[20px] leading-[1.3] font-semibold tracking-[-0.015em] text-balance text-ink focus:outline-none sm:text-[22px]"
        >
          {subject}
        </h2>

        {classification ? (
          <SortedAs
            // Keys must differ between siblings: a shared key (with DraftReply)
            // left old "Sorted as" rows on screen after opening another email.
            key={`sorted-${email.id}`}
            email={email}
            onCorrect={onCorrect}
            onUndo={onUndoCorrection}
            onRemoveRule={onRemoveRule}
            onSetPriority={onSetPriority}
          />
        ) : (
          <p
            className={`mt-1.5 text-[13px] ${email.classifyError ? "text-action-now-fg" : "text-muted"}`}
          >
            {email.classifyError
              ? `Could not classify: ${email.classifyError}`
              : "Not sorted yet"}
          </p>
        )}

        {/* The job list or the event card already shows these facts; the reply button stays. */}
        {showFacts ? (
          <FactsStrip facts={facts} link={email.poster ? undefined : links[0]} extra={actions} />
        ) : actions ? (
          <div className="mt-2 flex flex-wrap gap-2">{actions}</div>
        ) : null}
        {canReply && draftOpen ? (
          <DraftReply key={`draft-${email.id}`} email={email} onDraft={onDraftReply} autoStart />
        ) : null}

        {dates.length > 0 ? (
          <div className="mt-2 flex items-start gap-2 rounded-lg bg-highlight-soft px-3 py-1.5">
            <CalendarClock className="mt-[3px] h-3.5 w-3.5 shrink-0 text-highlight-dark" aria-hidden="true" />
            <ul className="flex min-w-0 flex-1 flex-col gap-1">
              {dates.map((item, index) => (
                <li key={`${item.date}-${index}`} className="flex items-start gap-2">
                  <details className="group min-w-0 flex-1">
                    <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2 text-[13px] [&::-webkit-details-marker]:hidden">
                      <span className="font-semibold text-ink">{item.label}</span>
                      <span className="text-ink">{formatDeadline(item)}</span>
                      {item.location ? (
                        <span className="text-[12px] text-muted">· {item.location}</span>
                      ) : null}
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
                  <CalendarChoice
                    automatic={addsItself(email, item)}
                    added={isInCalendar?.(deadlineKey(email.id, index)) ?? false}
                    onToggle={
                      onToggleCalendar
                        ? (on) => onToggleCalendar(deadlineKey(email.id, index), on)
                        : undefined
                    }
                  />
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <PosterCard email={email} />
        {email.jobs ? <JobsCard jobs={email.jobs.items} moreUrl={email.jobs.moreUrl} /> : null}

        {bodyParagraphs.length > 0 && email.jobs ? (
          // The job list above is the useful part; the flattened digest text folds away.
          <details className={FOLD}>
            <summary className={FOLD_SUMMARY}>
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
          <CleanBodyView paragraphs={bodyParagraphs} />
        ) : null}

        {links.length > 1 && !email.jobs ? (
          <details className={FOLD}>
            <summary className={FOLD_SUMMARY}>
              {links.length - 1} more link{links.length === 2 ? "" : "s"} in this email
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

        {ocrText ? (
          <details className={FOLD}>
            <summary className={FOLD_SUMMARY}>
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

type SortedAsProps = Omit<ComponentProps<typeof CorrectionControl>, "extra"> & {
  onSetPriority: (id: string, stars: number | null) => Promise<void>;
};

/** One compact line: its priority and what it was sorted as, plus "Why?" (the priority's reasons) and "Fix label". */
function SortedAs({ onSetPriority, ...props }: SortedAsProps) {
  const classification = props.email.classification;
  const [showReason, setShowReason] = useState(false);
  const reasonId = useId();
  if (!classification) return null;
  // "Why?" explains the priority (the sorting model's own sentence is not shown here).
  const reasons = classification.priority ? explainPriority(classification.priority) : [];

  return (
    <div className="mt-1.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="label text-muted">Priority</span>
        <PriorityEditor
          priority={classification.priority}
          onChange={(stars) => onSetPriority(props.email.id, stars)}
        />
        <CategoryBadge category={classification.category} />
        <StatusBadge action={classification.action} />
        <CorrectionControl
          {...props}
          extra={
            reasons.length > 0 ? (
              <button
                type="button"
                aria-expanded={showReason}
                aria-controls={reasonId}
                onClick={() => setShowReason((open) => !open)}
                className="inline-flex min-h-11 items-center rounded-lg px-1.5 text-[13px] text-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none sm:min-h-8"
              >
                Why?
              </button>
            ) : null
          }
        />
      </div>
      {reasons.length > 0 && showReason ? (
        <ul id={reasonId} className="mt-1 list-disc pl-5 text-[13px] leading-5 text-ink/80 marker:text-muted">
          {reasons.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
    </div>
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

// The folded cards (original email, signature, earlier messages, links, image text):
// one compact row when closed.
const FOLD =
  "mt-1.5 rounded-lg border border-line px-3 [&[open]]:pb-1 [&[open]>summary]:mb-0.5";
const FOLD_SUMMARY =
  "flex min-h-7 cursor-pointer items-center text-[12.5px] text-muted hover:text-ink";

/**
 * The message itself first; the signature, footer boilerplate and quoted older
 * messages fold away (see domain/cleanBody.ts). Nothing is removed.
 */
function CleanBodyView({ paragraphs }: { paragraphs: readonly string[] }) {
  const { main, footer, earlier } = cleanBody(paragraphs);

  return (
    <>
      <div className="mt-5 max-w-[68ch] border-t border-line pt-5 text-[15px] leading-7 break-words text-ink/90 space-y-4 sm:text-[16px]">
        {toBlocks(main).map((block, index) => (
          <BodyBlock key={index} block={block} />
        ))}
      </div>

      {footer.length > 0 ? (
        <details className={FOLD}>
          <summary className={FOLD_SUMMARY}>Show signature and footer</summary>
          <div className="space-y-2 pb-2 text-[13px] leading-5 break-words text-ink/70">
            {footer.map((paragraph, index) => (
              <p key={index} className="whitespace-pre-wrap">
                <LinkedText text={paragraph} />
              </p>
            ))}
          </div>
        </details>
      ) : null}

      {earlier.length > 0 ? (
        <details className={FOLD}>
          <summary className={FOLD_SUMMARY}>Show earlier messages in this thread</summary>
          <div className="space-y-2 border-l-2 border-line pb-2 pl-3 text-[13px] leading-5 break-words text-ink/70">
            {earlier.map((paragraph, index) => (
              <p key={index} className="whitespace-pre-wrap">
                <LinkedText text={paragraph} />
              </p>
            ))}
          </div>
        </details>
      ) : null}
    </>
  );
}

/** One readable block: a heading, a list, or a paragraph with "Label: value" lines. */
function BodyBlock({ block }: { block: Block }) {
  if (block.kind === "h") {
    return (
      <h3 className="pt-1 text-[12px] font-semibold tracking-[0.06em] text-muted uppercase">{block.text}</h3>
    );
  }
  if (block.kind !== "p") {
    const List = block.kind;
    return (
      <List className={`space-y-1 pl-5 ${block.kind === "ul" ? "list-disc" : "list-decimal"} marker:text-muted`}>
        {block.items.map((item, index) => (
          <li key={index}>
            <RichText text={item} />
          </li>
        ))}
      </List>
    );
  }
  return (
    <p className="whitespace-pre-wrap">
      {block.text.split("\n").map((line, index) => {
        const pair = labelValue(line);
        return (
          <span key={index}>
            {index > 0 ? "\n" : null}
            {pair ? (
              <>
                <strong className="font-semibold text-ink">{pair[0]}:</strong> <RichText text={pair[1]} />
              </>
            ) : (
              <RichText text={line} />
            )}
          </span>
        );
      })}
    </p>
  );
}

/** Links as small icons, dates and times softly marked. */
function RichText({ text }: { text: string }) {
  const parts = text.split(/<(https?:\/\/[^>\s]+)>/g);
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <LinkedText key={index} text={`<${part}>`} />
        ) : (
          markWhen(part).map((piece, at) =>
            piece.mark ? (
              <mark key={`${index}-${at}`} className="rounded bg-highlight-soft px-0.5 text-ink">
                {piece.text}
              </mark>
            ) : (
              <span key={`${index}-${at}`}>{piece.text}</span>
            ),
          )
        ),
      )}
    </>
  );
}


/**
 * Whether a date from this email is in the calendar and to-do list. Canvas due dates
 * go in by themselves; any other date is the student's choice.
 */
function CalendarChoice({
  automatic,
  added,
  onToggle,
}: {
  automatic: boolean;
  added: boolean;
  onToggle?: (inCalendar: boolean) => void;
}) {
  if (automatic) {
    return (
      <span
        className="inline-flex shrink-0 items-center gap-1 text-[12px] text-muted"
        title="Canvas assignments are added to your calendar automatically"
      >
        <CalendarCheck className="h-3.5 w-3.5" aria-hidden="true" />
        In calendar
      </span>
    );
  }
  if (!onToggle) {
    return null;
  }
  return (
    <button
      type="button"
      aria-pressed={added}
      onClick={() => onToggle(!added)}
      title={added ? "Remove from your calendar and to-do list" : "Add to your calendar and to-do list"}
      className={`inline-flex min-h-7 shrink-0 items-center gap-1 rounded-full border px-2.5 text-[12px] font-medium focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
        added
          ? "border-accent bg-accent text-white hover:bg-accent-dark"
          : "border-line bg-surface text-ink hover:bg-surface-muted"
      }`}
    >
      {added ? (
        <CalendarCheck className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <CalendarPlus className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {added ? "In calendar" : "Add to calendar"}
    </button>
  );
}
