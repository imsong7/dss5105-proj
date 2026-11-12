import type { ActionKey, CategoryKey } from "./taxonomy";

/**
 * Frontend inbox model. The Flask DTO (`content_category`, `reply_nature`,
 * `deadline_candidate`, ...) is mapped into this shape by services/flask.ts.
 */

export interface DeadlineCandidate {
  /** Short human label, e.g. "Deadline" or "Exam". */
  label: string;
  /** Calendar date in YYYY-MM-DD form. */
  date: string;
  /** 24-hour time in HH:mm form. Omitted for all-day events. */
  time?: string;
  /** Display timezone, e.g. "SGT". */
  timezone: string;
  /** Text in the email the date was read from. */
  evidence?: string;
  /** True when the email gave no year and one was inferred. */
  yearInferred?: boolean;
  /** True when the date was read off a poster image. */
  fromImage?: boolean;
}

/** One posting from a job digest (NUS TalentConnect), see app/listings.py. */
export interface Job {
  id: string;
  url: string;
  title: string;
  company: string;
  easyApply: boolean;
  /** "Internship", "Full time", ... */
  type: string;
  /** "Remote", "Hybrid" or "Office". */
  mode: string;
  location: string;
  /** e.g. "Dec '26 - May/Jun '27". */
  period: string;
  /** e.g. "SGD 1,000–1,200/mo"; empty when not stated. */
  pay: string;
  /** e.g. "UPIP" or a module code. */
  programme: string;
}

/** What a poster image (or the email text) says about an event, as facts the student can act on. */
export interface EmailPoster {
  title: string;
  /** YYYY-MM-DD of the event, when the poster shows one. */
  date?: string;
  /** As written, e.g. "2pm - 5pm". */
  time?: string;
  venue: string;
  /** "qr" links come from a QR code on the poster. */
  links: readonly { url: string; source: "qr" | "text" }[];
  hasImage: boolean;
}

export interface EmailClassification {
  category: CategoryKey;
  action: ActionKey;
  reason: string;
  /** True when the student fixed the labels by hand. */
  corrected?: boolean;
  /** True when a "always do this for this sender" rule decided the labels. */
  byRule?: boolean;
  /** The model's labels before a correction, so it can be undone. */
  original?: { category: CategoryKey; action: ActionKey };
  /** Which backend produced this result, so switching backends does not reuse stale answers. */
  backend?: string;
}

export interface ReplyDraft {
  reply: string;
  placeholders: readonly string[];
  guardrailIssues: readonly string[];
  provider: string;
  model: string;
}

export interface InboxEmail {
  id: string;
  sender: {
    name: string;
    address: string;
  };
  subject: string;
  preview: string;
  body: string;
  /** ISO 8601 timestamp with an explicit offset. */
  receivedAt: string;
  /** Found by the backend without a model, so it exists before classification. */
  deadline?: DeadlineCandidate;
  /** Every date found in the email, in reading order. The first is `deadline`. */
  deadlines?: readonly DeadlineCandidate[];
  /** Absent until the email has been classified. */
  classification?: EmailClassification;
  /** Set when classification of this email failed. */
  classifyError?: string;
  /** Text read from images by OCR (already part of `body`). */
  ocrText?: string;
  /** Facts found on a poster image in the email. */
  poster?: EmailPoster;
  /** Opens the original message in Outlook on the web. */
  webLink?: string;
  /** An event announced in the email text (shown when there is no poster). */
  event?: EmailPoster;
  /** Jobs listed in a job digest, with the digest's "view more" link. */
  jobs?: { items: readonly Job[]; moreUrl: string };
}

export type SortOrder = "newest" | "oldest";

export type ActionFilter = ActionKey | "all";

/** Days back from now, 0 for no limit, or "custom" to use a DateRange. */
export type WindowDays = 1 | 7 | 30 | 90 | 0 | "custom";

/** Inclusive YYYY-MM-DD bounds in local time. An empty string leaves that side open. */
export interface DateRange {
  since: string;
  before: string;
}

export interface InboxFilters {
  query: string;
  action: ActionFilter;
  categories: readonly CategoryKey[];
}
