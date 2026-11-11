import type {
  DeadlineCandidate,
  EmailClassification,
  InboxEmail,
  Job,
  ReplyDraft,
} from "../domain/email";
import type {
  AcademicEvent,
  PersonalEvent,
  PersonalEventDraft,
} from "../domain/calendar";
import type { ActionKey, CategoryKey } from "../domain/taxonomy";
import { ACTION_KEYS, CATEGORY_KEYS } from "../domain/taxonomy";
import { api } from "./api";

/* ---- Flask payloads (see app/server.py, app/schemas.py, app/calendar.py) ---- */

export interface FlaskDeadline {
  date: string;
  all_day: boolean;
  timezone: string;
  text: string;
  year_inferred: boolean;
  event_type: "exam" | "deadline";
  due_at?: string;
  /** True when the date was read off a poster image. */
  from_image?: boolean;
}

/** One job from a digest (app/listings.py). */
export interface FlaskJob {
  id: string;
  url: string;
  title: string;
  company: string;
  easy_apply: boolean;
  type: string;
  mode: string;
  location: string;
  period: string;
  pay: string;
  programme: string;
}

function mapJob(raw: FlaskJob): Job {
  return {
    id: raw.id,
    url: raw.url,
    title: raw.title,
    company: raw.company,
    easyApply: Boolean(raw.easy_apply),
    type: raw.type || "",
    mode: raw.mode || "",
    location: raw.location || "",
    period: raw.period || "",
    pay: raw.pay || "",
    programme: raw.programme || "",
  };
}

function jobToFlask(job: Job): FlaskJob {
  return {
    id: job.id,
    url: job.url,
    title: job.title,
    company: job.company,
    easy_apply: job.easyApply,
    type: job.type,
    mode: job.mode,
    location: job.location,
    period: job.period,
    pay: job.pay,
    programme: job.programme,
  };
}

/* ---- Saved jobs ---- */

export async function fetchSavedJobs(signal?: AbortSignal): Promise<Job[]> {
  const data = await api<{ jobs: FlaskJob[] }>("/api/saved-jobs", undefined, { signal, timeoutMs: 10_000 });
  return data.jobs.map(mapJob);
}

export async function saveJob(job: Job): Promise<Job> {
  const data = await api<{ job: FlaskJob }>("/api/saved-jobs", jobToFlask(job), { timeoutMs: 10_000 });
  return mapJob(data.job);
}

export async function removeSavedJob(id: string): Promise<void> {
  await api(`/api/saved-jobs/${encodeURIComponent(id)}`, undefined, { method: "DELETE", timeoutMs: 10_000 });
}

/** Facts read off a poster image (app/poster.py). */
export interface FlaskPoster {
  title: string;
  when: { date: string; time?: string; year_inferred?: boolean } | null;
  venue: string;
  links: { url: string; source: "qr" | "text" }[];
  has_image: boolean;
}

export interface FlaskEmail {
  id: string;
  /** A result the student already has (correction, sender rule or cache). */
  saved_classification?: FlaskClassification | null;
  subject: string;
  sender: string;
  received: string;
  preview: string;
  body: string;
  text_source?: string;
  ocr_confidence?: number | null;
  ocr_notes?: string[];
  /** The OCR part of `body`; shown folded away, not as body text. */
  ocr_text?: string;
  poster?: FlaskPoster | null;
  jobs?: { jobs: FlaskJob[]; more_url: string } | null;
  deadline_candidate?: FlaskDeadline | null;
  deadline_candidates?: FlaskDeadline[];
}

interface FlaskReplyDraft {
  reply: string;
  placeholders?: string[];
  guardrail_issues?: string[];
  provider?: string;
  model?: string;
}

interface FlaskClassification {
  content_category: string;
  reply_nature: string;
  reason: string;
  corrected?: boolean;
  rule?: boolean;
  original?: { content_category: string; reply_nature: string };
}

export interface SessionInfo {
  email: string;
  /** Display name chosen at sign-up or in the app; empty when none was set. */
  name: string;
  provider: MailSource;
  /** True when a signed-in student may switch between their flow and a token. */
  canChooseSource?: boolean;
  /** Set when the student signed in with an Outlook token instead of an account. */
  graphToken?: string;
  maxEmails: number;
}

export type MailSource = "outlook" | "powerautomate";

/** Save where this student's mail comes from. The page reloads afterwards. */
export async function saveMailSource(source: MailSource): Promise<void> {
  await api("/api/profile", { source }, { timeoutMs: 10_000 });
}

export interface BackendInfo {
  id: string;
  label: string;
  description: string;
  ready: boolean | null;
}

export interface Health {
  ready: boolean | null;
  detail: string;
}

/* ---- Mapping ---- */

/** "Name <addr@x.y>" -> parts; a bare address uses its local part as the name. */
export function parseSender(raw: string): { name: string; address: string } {
  const text = (raw || "").trim();
  const match = text.match(/^(.*?)\s*<([^>]+)>$/);

  if (match) {
    const address = match[2].trim();
    const name = match[1].replace(/^["']|["']$/g, "").trim();
    return { name: name || address, address };
  }

  if (text.includes("@")) {
    return { name: text.split("@")[0], address: text };
  }

  return { name: text || "Unknown sender", address: "" };
}

function mapDeadline(candidate: FlaskDeadline | null | undefined): DeadlineCandidate | undefined {
  if (!candidate) {
    return undefined;
  }

  return {
    label: candidate.event_type === "exam" ? "Exam" : "Deadline",
    date: candidate.date,
    time: candidate.due_at ? candidate.due_at.slice(11, 16) : undefined,
    timezone:
      candidate.timezone === "Asia/Singapore" ? "SGT" : candidate.timezone,
    evidence: candidate.text,
    yearInferred: candidate.year_inferred,
    fromImage: candidate.from_image || undefined,
  };
}

export function mapEmail(raw: FlaskEmail): InboxEmail {
  return {
    id: raw.id,
    sender: parseSender(raw.sender),
    subject: raw.subject || "(no subject)",
    preview: raw.preview || "",
    body: raw.body || raw.preview || "",
    receivedAt: raw.received,
    ocrText: raw.ocr_text || undefined,
    poster: raw.poster
      ? {
          title: raw.poster.title,
          date: raw.poster.when?.date,
          time: raw.poster.when?.time,
          venue: raw.poster.venue,
          links: raw.poster.links,
          hasImage: raw.poster.has_image,
        }
      : undefined,
    jobs: raw.jobs?.jobs.length
      ? { items: raw.jobs.jobs.map(mapJob), moreUrl: raw.jobs.more_url }
      : undefined,
    deadline: mapDeadline(raw.deadline_candidate),
    deadlines: (raw.deadline_candidates ?? [])
      .map(mapDeadline)
      .filter((item): item is DeadlineCandidate => item !== undefined),
  };
}

function categoryOf(value: string): CategoryKey {
  return (CATEGORY_KEYS as string[]).includes(value)
    ? (value as CategoryKey)
    : "others";
}

function actionOf(value: string): ActionKey {
  return (ACTION_KEYS as string[]).includes(value)
    ? (value as ActionKey)
    : "no_immediate_action";
}

export function mapClassification(raw: FlaskClassification): EmailClassification {
  return {
    category: categoryOf(raw.content_category),
    action: actionOf(raw.reply_nature),
    reason: raw.reason || "",
    corrected: raw.corrected || undefined,
    byRule: raw.rule || undefined,
    original: raw.original
      ? {
          category: categoryOf(raw.original.content_category),
          action: actionOf(raw.original.reply_nature),
        }
      : undefined,
  };
}

/* ---- Calls ---- */

export function fetchSession(signal?: AbortSignal): Promise<SessionInfo> {
  return api<SessionInfo>("/api/session", undefined, { signal, timeoutMs: 10_000 });
}

export async function fetchEmails(
  params: {
    provider: string;
    token: string;
    count: number;
    since?: string;
    before?: string;
    /** Saved results for this model come back with the mail. */
    backend?: string;
  },
  signal?: AbortSignal,
): Promise<{ raw: FlaskEmail[]; emails: InboxEmail[] }> {
  const data = await api<{ emails: FlaskEmail[] }>(
    "/api/emails",
    {
      provider: params.provider,
      credentials: params.provider === "outlook" ? { token: params.token } : {},
      count: params.count,
      ...(params.since ? { since: params.since } : {}),
      ...(params.before ? { before: params.before } : {}),
      ...(params.backend ? { backend: params.backend } : {}),
    },
    { signal, timeoutMs: 60_000 },
  );

  // Already-sorted mail arrives sorted, so reloading the page does not re-sort it.
  const emails = data.emails.map((item) => {
    const email = mapEmail(item);
    return item.saved_classification
      ? { ...email, classification: mapClassification(item.saved_classification) }
      : email;
  });
  return { raw: data.emails, emails };
}

export async function draftReply(
  email: FlaskEmail,
  signal?: AbortSignal,
): Promise<ReplyDraft> {
  const result = await api<FlaskReplyDraft>(
    "/api/draft-reply",
    { email },
    { signal, timeoutMs: 120_000 },
  );

  return {
    reply: result.reply || "",
    placeholders: result.placeholders ?? [],
    guardrailIssues: result.guardrail_issues ?? [],
    provider: result.provider ?? "",
    model: result.model ?? "",
  };
}

export async function sendReply(
  email: FlaskEmail,
  reply: string,
  token?: string,
): Promise<void> {
  await api(
    "/api/send-reply",
    { email, reply, token: token?.trim() || undefined },
    { timeoutMs: 30_000 },
  );
}

export async function classifyEmail(
  email: FlaskEmail,
  backend: string,
  signal?: AbortSignal,
): Promise<EmailClassification> {
  const result = await api<FlaskClassification>(
    "/api/classify",
    { email, backend },
    { signal, timeoutMs: 180_000 },
  );

  return mapClassification(result);
}

export async function fetchBackends(
  signal?: AbortSignal,
): Promise<{ backends: BackendInfo[]; default: string }> {
  const data = await api<{
    backends: { id: string; label: string; description?: string; ready?: boolean | null }[];
    default: string;
  }>("/api/backends", undefined, { signal, timeoutMs: 10_000 });

  return {
    default: data.default,
    backends: data.backends.map((item) => ({
      id: item.id,
      label: item.label,
      description: item.description ?? "",
      ready: item.ready ?? null,
    })),
  };
}

export async function fetchHealth(
  backend: string,
  signal?: AbortSignal,
): Promise<Health> {
  try {
    const data = await api<{ backend_ready: boolean | null }>(
      `/api/health?backend=${encodeURIComponent(backend)}`,
      undefined,
      { signal, timeoutMs: 10_000 },
    );
    const ready = data.backend_ready;
    return {
      ready,
      detail:
        ready === true
          ? "Model ready."
          : ready === false
            ? "This model is not ready. Pick another one, or see the README section on choosing a backend."
            : "Model readiness is unknown.",
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    return { ready: false, detail: "Could not reach the server." };
  }
}

export async function fetchAcademicCalendar(
  signal?: AbortSignal,
): Promise<{ label: string; events: AcademicEvent[] }> {
  try {
    const data = await api<{
      label: string;
      events: {
        category: string;
        event: string;
        start_date: string;
        end_date: string;
        notes: string;
        mark?: boolean;
      }[];
    }>("/api/academic-calendar", undefined, { signal, timeoutMs: 10_000 });

    return {
      label: data.label,
      events: data.events.map((item) => ({
        category: item.category,
        event: item.event,
        startDate: item.start_date,
        endDate: item.end_date,
        notes: item.notes,
        mark: Boolean(item.mark),
      })),
    };
  } catch {
    // A missing CSV must not block the mailbox.
    return { label: "", events: [] };
  }
}

/** Power Automate only: ask the flow to push the newest mail. */
export async function requestFlowRefresh(): Promise<void> {
  const since = new Date(Date.now() - 90 * 86_400_000).toISOString();
  await api("/api/inbound/refresh", { since }, { timeoutMs: 20_000 });
}

export async function fetchRefreshConfigured(): Promise<boolean> {
  try {
    const data = await api<{ refresh_configured?: boolean }>(
      "/api/inbound/diagnostics",
      undefined,
      { timeoutMs: 8_000 },
    );
    return Boolean(data.refresh_configured);
  } catch {
    return false;
  }
}

/* ---- Personal calendar events ---- */

export async function fetchPersonalEvents(
  signal?: AbortSignal,
): Promise<PersonalEvent[]> {
  const data = await api<{ events: PersonalEvent[] }>("/api/events", undefined, {
    signal,
    timeoutMs: 10_000,
  });
  return data.events;
}

export function createPersonalEvent(draft: PersonalEventDraft): Promise<PersonalEvent> {
  return api<PersonalEvent>("/api/events", draft, { timeoutMs: 10_000 });
}

export function updatePersonalEvent(
  id: string,
  draft: PersonalEventDraft,
): Promise<PersonalEvent> {
  return api<PersonalEvent>(`/api/events/${encodeURIComponent(id)}`, draft, {
    timeoutMs: 10_000,
    method: "PUT",
  });
}

export async function deletePersonalEvent(id: string): Promise<void> {
  await api(`/api/events/${encodeURIComponent(id)}`, undefined, {
    timeoutMs: 10_000,
    method: "DELETE",
  });
}

/* ---- Corrections ---- */

export async function saveCorrection(
  email: FlaskEmail,
  backend: string,
  original: { category: CategoryKey; action: ActionKey },
  category: CategoryKey,
  action: ActionKey,
  rememberSender = false,
): Promise<void> {
  await api(
    "/api/corrections",
    {
      email: {
        id: email.id,
        subject: email.subject,
        sender: email.sender,
        received: email.received,
        preview: email.preview,
      },
      backend,
      original: {
        content_category: original.category,
        reply_nature: original.action,
      },
      content_category: category,
      reply_nature: action,
      remember_sender: rememberSender,
    },
    { timeoutMs: 10_000 },
  );
}

export async function deleteSenderRule(address: string): Promise<void> {
  await api(`/api/sender-rules?sender=${encodeURIComponent(address)}`, undefined, {
    timeoutMs: 10_000,
    method: "DELETE",
  });
}

export async function deleteCorrection(id: string): Promise<void> {
  await api(`/api/corrections/${encodeURIComponent(id)}`, undefined, {
    timeoutMs: 10_000,
    method: "DELETE",
  });
}

/* ---- Done and snoozed items ---- */

export interface ItemState {
  done: boolean;
  snoozedUntil: string;
  /** ISO time the mark was made. Used for "cleared this week". */
  at?: string;
}

export async function fetchItemStates(
  signal?: AbortSignal,
): Promise<Record<string, ItemState>> {
  const data = await api<{
    states: Record<string, { done: boolean; snoozed_until: string; at?: string }>;
  }>("/api/item-states", undefined, { signal, timeoutMs: 10_000 });

  return Object.fromEntries(
    Object.entries(data.states).map(([key, value]) => [
      key,
      { done: Boolean(value.done), snoozedUntil: value.snoozed_until || "", at: value.at },
    ]),
  );
}

export async function saveItemState(
  key: string,
  state: ItemState | null,
): Promise<void> {
  await api(
    "/api/item-states",
    {
      key,
      done: state?.done ?? false,
      snoozed_until: state?.snoozedUntil ?? "",
    },
    { timeoutMs: 10_000 },
  );
}

/* ---- Calendar feed ---- */

export interface FeedLinks {
  url: string;
  webcal: string;
}

export function fetchFeed(): Promise<FeedLinks> {
  return api<FeedLinks>("/api/feed", undefined, { timeoutMs: 10_000 });
}

export function rotateFeed(): Promise<FeedLinks> {
  return api<FeedLinks>("/api/feed/rotate", {}, { timeoutMs: 10_000 });
}

export interface FeedItem {
  key: string;
  title: string;
  date: string;
  time: string;
  detail: string;
  url: string;
}

export async function syncFeed(items: FeedItem[]): Promise<void> {
  await api("/api/feed/sync", { items }, { timeoutMs: 15_000 });
}

/* ---- Profile ---- */

/** Save the display name. An empty name goes back to the default. */
export async function saveName(name: string): Promise<string> {
  const data = await api<{ name: string }>("/api/profile", { name }, { timeoutMs: 10_000 });
  return data.name;
}

/* ---- Outlook flow setup ---- */

export interface SetupInfo {
  endpoint: string;
  email: string;
  token: string;
  /** True once the imported flow's HTTP address is saved. */
  flow_url_saved?: boolean;
}

export function fetchSetup(signal?: AbortSignal): Promise<SetupInfo> {
  return api<SetupInfo>("/api/setup", undefined, { signal, timeoutMs: 10_000 });
}

/** Ready-made flow for this account (download link, same origin). */
export const FLOW_PACKAGE_URL = "/api/setup/flow.zip";

export async function saveFlowUrl(url: string): Promise<boolean> {
  const data = await api<{ saved: boolean }>("/api/setup/flow-url", { url }, { timeoutMs: 10_000 });
  return data.saved;
}
