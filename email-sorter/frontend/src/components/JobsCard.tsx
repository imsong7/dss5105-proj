import { Bookmark, BookmarkCheck, ExternalLink, Zap } from "lucide-react";
import { useState } from "react";

import type { Job } from "../domain/email";
import { useSavedJobs } from "../contexts/SavedJobsContext";

type Filter = "internship" | "paid" | "easy";

const FILTERS: readonly { key: Filter; label: string; test: (job: Job) => boolean }[] = [
  { key: "internship", label: "Internships", test: (job) => job.type === "Internship" },
  { key: "paid", label: "Paid", test: (job) => job.pay !== "" },
  { key: "easy", label: "Easy Apply", test: (job) => job.easyApply },
];

const CHIP =
  "inline-flex min-h-8 items-center rounded-full border px-3 text-[12px] font-medium focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none";

/** Two letters for the company badge: "Singapore General Hospital" -> "SG". */
function initials(company: string, title: string): string {
  const words = (company || title).replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((word) => word[0].toUpperCase()).join("") || "J";
}

const TAG = "inline-flex items-center rounded-full px-2 py-0.5 text-[11.5px] font-medium whitespace-nowrap";

/** One job: company badge, title, company, tags, pay; Save and Open on the right. */
export function JobRow({ job }: { job: Job }) {
  const saved = useSavedJobs();
  const isSaved = saved?.isSaved(job.id) ?? false;

  return (
    <li className="flex items-start gap-3 py-3.5">
      <span
        aria-hidden="true"
        className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-[13px] font-bold tracking-[0.02em] text-accent"
      >
        {initials(job.company, job.title)}
      </span>

      <div className="min-w-0 flex-1">
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[14px] leading-5 font-semibold text-ink hover:text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          {job.title}
        </a>
        {job.company ? <p className="mt-0.5 text-[13px] text-muted">{job.company}</p> : null}

        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {job.easyApply ? (
            <span className={`${TAG} gap-1 bg-accent text-white`}>
              <Zap className="h-3 w-3" aria-hidden="true" />
              Easy Apply
            </span>
          ) : null}
          {job.type ? <span className={`${TAG} bg-surface-muted text-ink`}>{job.type}</span> : null}
          {job.mode ? <span className={`${TAG} bg-surface-muted text-ink`}>{job.mode}</span> : null}
          {job.period ? <span className={`${TAG} bg-surface-muted text-muted`}>{job.period}</span> : null}
        </div>
        {job.pay ? <p className="mt-1.5 text-[13px] font-semibold text-ink">{job.pay}</p> : null}
      </div>

      <div className="flex shrink-0 items-center">
        {saved ? (
          <button
            type="button"
            onClick={() => void saved.toggle(job)}
            aria-pressed={isSaved}
            aria-label={isSaved ? `Remove ${job.title} from saved jobs` : `Save ${job.title}`}
            title={isSaved ? "Saved" : "Save job"}
            className={`grid h-10 w-10 place-items-center rounded-full hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
              isSaved ? "text-accent" : "text-muted"
            }`}
          >
            {isSaved ? <BookmarkCheck className="h-[18px] w-[18px]" /> : <Bookmark className="h-[18px] w-[18px]" />}
          </button>
        ) : null}
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${job.title}`}
          className="grid h-10 w-10 place-items-center rounded-full text-muted hover:bg-surface-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <ExternalLink className="h-4 w-4" aria-hidden="true" />
        </a>
      </div>
    </li>
  );
}

/** The jobs in a digest email, with quick filters and a link to the full list. */
export function JobsCard({ jobs, moreUrl }: { jobs: readonly Job[]; moreUrl: string }) {
  const [active, setActive] = useState<readonly Filter[]>([]);
  const shown = jobs.filter((job) =>
    active.every((key) => FILTERS.find((filter) => filter.key === key)?.test(job)),
  );

  return (
    <section aria-label="Jobs in this email" className="mt-3 rounded-xl border border-line bg-surface px-3.5 pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[14px] font-semibold text-ink">
          Jobs in this email <span className="font-normal text-muted">· {jobs.length}</span>
        </h3>
        {moreUrl ? (
          <a
            href={moreUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto inline-flex min-h-8 items-center gap-1 text-[13px] font-medium text-accent hover:underline"
          >
            View more jobs
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        ) : null}
      </div>

      <div role="group" aria-label="Filter jobs" className="mt-2 flex flex-wrap gap-1.5">
        {FILTERS.map((filter) => {
          const on = active.includes(filter.key);
          return (
            <button
              key={filter.key}
              type="button"
              aria-pressed={on}
              onClick={() =>
                setActive((current) =>
                  on ? current.filter((key) => key !== filter.key) : [...current, filter.key],
                )
              }
              className={`${CHIP} ${on ? "border-accent bg-accent-soft text-accent" : "border-line text-muted hover:text-ink"}`}
            >
              {filter.label}
            </button>
          );
        })}
      </div>

      {shown.length > 0 ? (
        <ul className="mt-1 divide-y divide-line">
          {shown.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </ul>
      ) : (
        <p className="py-4 text-[13px] text-muted">No jobs match these filters.</p>
      )}
    </section>
  );
}
