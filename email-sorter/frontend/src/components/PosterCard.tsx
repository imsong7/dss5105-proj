import { CalendarDays, ExternalLink, MapPin, QrCode } from "lucide-react";
import { useState } from "react";

import { formatDayShort } from "../domain/calendar";
import type { InboxEmail } from "../domain/email";
import { linkLabel } from "../domain/links";

/**
 * What a poster image in the email says, as a few facts and buttons instead
 * of raw OCR text: the event, when and where, and its links (a QR code's link
 * first). The preview comes from the server and is only served to its owner.
 * Without a poster, an event announced in the email text gets the same card.
 */
export function PosterCard({ email }: { email: InboxEmail }) {
  // A preview that fails to load is hidden rather than shown as a broken image.
  const [failedFor, setFailedFor] = useState<string | null>(null);
  const poster = email.poster ?? email.event;
  if (!poster) {
    return null;
  }
  const heading = email.poster ? "From the poster" : "Event";

  const preview = `/api/emails/${encodeURIComponent(email.id)}/poster.jpg`;
  const when = poster.date
    ? `${formatDayShort(poster.date)}${poster.time ? ` · ${poster.time}` : ""}`
    : "";

  return (
    <section
      aria-label={heading}
      className="mt-3 flex gap-3 rounded-xl border border-line bg-surface p-3"
    >
      {poster.hasImage && failedFor !== email.id ? (
        <a
          href={preview}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          aria-label="Open the poster preview"
        >
          <img
            src={preview}
            alt=""
            loading="lazy"
            onError={() => setFailedFor(email.id)}
            className="h-28 w-20 rounded-lg border border-line object-cover object-top sm:h-32 sm:w-24"
          />
        </a>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <p className="text-[11px] font-semibold tracking-[0.04em] text-muted uppercase">{heading}</p>
        {poster.title ? (
          <p className="text-[15px] leading-5 font-semibold text-ink">{poster.title}</p>
        ) : null}
        {when ? (
          <p className="flex items-center gap-1.5 text-[13px] text-ink">
            <CalendarDays className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden="true" />
            {when}
          </p>
        ) : null}
        {poster.venue ? (
          <p className="flex items-center gap-1.5 text-[13px] text-ink">
            <MapPin className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden="true" />
            <span className="truncate">{poster.venue}</span>
          </p>
        ) : null}

        {poster.links.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-2">
            {poster.links.map((link, index) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                title={link.url}
                className={`inline-flex min-h-10 items-center gap-1.5 rounded-[10px] px-3 text-[13px] font-semibold focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
                  index === 0
                    ? "bg-accent text-white hover:bg-accent-dark"
                    : "border border-line text-ink hover:bg-surface-muted"
                }`}
              >
                {link.source === "qr" ? (
                  <QrCode className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {linkLabel(link.url)}
                {link.source === "qr" ? <span className="sr-only"> (from the QR code)</span> : null}
              </a>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
