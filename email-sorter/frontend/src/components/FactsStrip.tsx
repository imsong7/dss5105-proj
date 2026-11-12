import { BookOpen, ExternalLink, MapPin, Video } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { useOpenCourse } from "../contexts/CourseContext";
import type { Fact, FactKind } from "../domain/keyFacts";

const ICONS: Record<FactKind, LucideIcon> = {
  place: MapPin,
  course: BookOpen,
  meeting: Video,
};

const ITEM = "inline-flex min-h-7 max-w-full items-center gap-1 text-[13px] text-ink/80";
const LINKISH = "rounded-sm hover:text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none";

/**
 * One compact line above the message: where, how much, which course, and the
 * email's main link as a small button at the end (Open form, Join Zoom, ...).
 */
export function FactsStrip({
  facts,
  link,
  extra,
}: {
  facts: readonly Fact[];
  link?: { url: string; label: string };
  /** Another action shown beside the link button (Draft a reply). */
  extra?: ReactNode;
}) {
  const openCourse = useOpenCourse();
  // A meeting link is the action; it goes in the button slot.
  const meeting = facts.find((fact) => fact.kind === "meeting");
  const action = meeting?.href ? { url: meeting.href, label: meeting.label } : link;
  const shown = facts.filter((fact) => fact.kind !== "meeting");
  if (shown.length === 0 && !action && !extra) {
    return null;
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3.5 gap-y-1">
      {shown.map((fact) => {
        const Icon = ICONS[fact.kind];
        const body = (
          <>
            <Icon className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden="true" />
            <span className="truncate">{fact.label}</span>
          </>
        );
        const key = `${fact.kind}-${fact.label}`;
        if (fact.href) {
          return (
            <a key={key} href={fact.href} target="_blank" rel="noopener noreferrer" className={`${ITEM} ${LINKISH}`}>
              {body}
            </a>
          );
        }
        if (fact.kind === "course" && openCourse) {
          return (
            <button
              key={key}
              type="button"
              onClick={() => openCourse(fact.label)}
              className={`${ITEM} ${LINKISH} font-semibold`}
            >
              {body}
            </button>
          );
        }
        return (
          <span key={key} className={ITEM}>
            {body}
          </span>
        );
      })}

      <div className="ml-auto flex flex-wrap items-center gap-2">
      {extra}
      {action ? (
        <a
          href={action.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-8 items-center gap-1.5 rounded-full bg-accent px-3 text-[13px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          {meeting ? <Video className="h-3.5 w-3.5" aria-hidden="true" /> : null}
          {action.label}
          {meeting ? null : <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />}
        </a>
      ) : null}
      </div>
    </div>
  );
}
