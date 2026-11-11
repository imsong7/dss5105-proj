import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  ActionFilter,
  DateRange,
  EmailClassification,
  InboxEmail,
  SortOrder,
  WindowDays,
} from "../domain/email";
import {
  countByAction,
  filterEmails,
  sortEmails,
  withinWindow,
} from "../domain/inbox";
import type { ActionKey, CategoryKey } from "../domain/taxonomy";
import { isAbort } from "../services/api";
import {
  classifyEmail,
  deleteCorrection,
  deleteSenderRule,
  draftReply as requestDraftReply,
  fetchBackends,
  fetchEmails,
  fetchHealth,
  fetchRefreshConfigured,
  requestFlowRefresh,
  saveCorrection,
  sendReply as requestSendReply,
} from "../services/flask";
import type {
  BackendInfo,
  FlaskEmail,
  Health,
  SessionInfo,
} from "../services/flask";

const CLASSIFY_CONCURRENCY = 6;

export type LoadPhase = "idle" | "loading" | "ready";

export interface Notice {
  text: string;
  error: boolean;
}

const PUSH_POLL_MS = 3_000;
const AUTO_SORT_KEY = "inbox-sorter.autoSort";
const WINDOW_KEY = "inbox-sorter.window";
const SORT_KEY = "inbox-sorter.sort";

function readPref(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writePref(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // The preference simply will not persist.
  }
}

function readWindow(): WindowDays {
  const stored = readPref(WINDOW_KEY);
  if (stored === "custom") return "custom";
  const value = Number(stored);
  return value === 1 || value === 7 || value === 30 || value === 90 || value === 0
    ? value
    : 90;
}

function readAutoSort(): boolean {
  try {
    return window.localStorage.getItem(AUTO_SORT_KEY) !== "off";
  } catch {
    return true;
  }
}
const DEFAULT_COUNT = 500;
/**
 * Pushed mail arrives a few at a time. Sorting each trickle would keep the model
 * busy for nothing, so wait for a batch: this many unsorted emails, or a quiet
 * spell after the last one arrived. The student can always sort by hand.
 */
const PUSH_SORT_BATCH = 100;
const PUSH_SORT_QUIET_MS = 30_000;
/** No new mail for this long means the flow has finished sending. */
const PUSH_ARRIVAL_QUIET_MS = 6_000;
/** Today and Calendar read the same mail, so never load less than this. */
const MIN_LOAD_DAYS = 30;

/** Server-side bounds for the chosen band, widened to MIN_LOAD_DAYS. */
function loadBounds(
  days: WindowDays,
  range: DateRange,
  now: number = Date.now(),
): { since?: string; before?: string } {
  const floor = now - MIN_LOAD_DAYS * 86_400_000;

  if (days === 0) {
    return {};
  }

  if (days === "custom") {
    const start = range.since ? Date.parse(`${range.since}T00:00:00`) : NaN;
    const end = range.before ? Date.parse(`${range.before}T23:59:59.999`) : NaN;
    const since = Number.isNaN(start) ? floor : Math.min(start, floor);
    return {
      since: new Date(since).toISOString(),
      ...(Number.isNaN(end) ? {} : { before: new Date(Math.max(end, now)).toISOString() }),
    };
  }

  return { since: new Date(Math.min(now - days * 86_400_000, floor)).toISOString() };
}

/** Lower-cased sender address, used to match a sender rule. */
function senderKey(sender: InboxEmail["sender"]): string {
  return sender.address.trim().toLowerCase();
}

function isDesktop(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(min-width: 1024px)").matches
  );
}

function isModelResultForBackend(
  classification: EmailClassification | undefined,
  backend: string,
): boolean {
  return Boolean(
    classification &&
      !classification.corrected &&
      !classification.byRule &&
      (!classification.backend || classification.backend === backend),
  );
}

function chooseMergedClassification(
  server: EmailClassification | undefined,
  local: EmailClassification | undefined,
  currentBackend: string,
): EmailClassification | undefined {
  // A correction returned by the server (e.g. from another session) always wins.
  if (server?.corrected) return server;

  // A sender rule from the server wins unless the student already corrected this email.
  if (server?.byRule) {
    return local?.corrected ? local : server;
  }

  // A cached model result from the current backend wins over any local model result,
  // but still loses to a local correction or sender rule.
  if (server && (!server.backend || server.backend === currentBackend)) {
    if (local?.corrected || local?.byRule) return local;
    return server;
  }

  // The server returned nothing usable. Keep local results that are explicitly
  // authoritative (corrections, rules) or already belong to the current backend.
  if (local?.corrected || local?.byRule) return local;
  if (isModelResultForBackend(local, currentBackend)) return local;

  return undefined;
}

/** Merge a fresh server list with what the page already knows.
 *
 * Server corrections/rules beat local model results, but local corrections/rules
 * are preserved when the server only has a cached model answer. Model results
 * from a different backend are dropped so switching backends does not show stale
 * answers as if they came from the new backend.
 */
function mergeEmails(
  previous: readonly InboxEmail[],
  next: readonly InboxEmail[],
  currentBackend: string,
): InboxEmail[] {
  const known = new Map(previous.map((email) => [email.id, email]));

  return next.map((email) => {
    const old = known.get(email.id);
    if (!old) return email;

    const nextClassification = chooseMergedClassification(
      email.classification,
      old.classification,
      currentBackend,
    );

    return {
      ...email,
      classification: nextClassification,
      // Clear an earlier error as soon as a saved result replaces it.
      classifyError: nextClassification ? undefined : old.classifyError,
    };
  });
}

export function useInboxView(session: SessionInfo) {
  const isPushed = session.provider === "powerautomate";

  const [emails, setEmails] = useState<readonly InboxEmail[]>([]);
  const raw = useRef(new Map<string, FlaskEmail>());
  const [phase, setPhase] = useState<LoadPhase>("idle");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const loadController = useRef<AbortController | null>(null);
  const classifyController = useRef<AbortController | null>(null);
  const classifyRun = useRef(0);
  // Loading and classification are independent: one finishing must not clear the other.
  const loading = useRef(false);
  const classifying = useRef(false);

  // A token pasted on the sign-in page arrives with the session: no second paste.
  const [token, setToken] = useState(session.graphToken ?? "");
  const [tokenDialogOpen, setTokenDialogOpen] = useState(
    session.provider === "outlook" && !session.graphToken,
  );

  const [backends, setBackends] = useState<readonly BackendInfo[]>([]);
  const [backend, setBackend] = useState("");
  // Read inside loads without making every load callback depend on it.
  const backendRef = useRef("");
  backendRef.current = backend;
  const [health, setHealth] = useState<Health | null>(null);

  const [autoSort, setAutoSortState] = useState(readAutoSort);
  // Set when the student cancels, so auto-sort does not restart by itself.
  const paused = useRef(false);
  const [autoPaused, setAutoPausedState] = useState(false);
  const [autoRun, setAutoRun] = useState(false);
  const setPaused = useCallback((value: boolean) => {
    paused.current = value;
    setAutoPausedState(value);
  }, []);

  /** Supersede any classification run and clear its state. Late results and the old
   *  run's `finally` then see a newer run id and leave the new state alone. */
  const stopClassification = useCallback(() => {
    classifyController.current?.abort();
    classifyController.current = null;
    classifyRun.current += 1;
    classifying.current = false;
    setProgress(null);
    setAutoRun(false);
  }, []);

  // When the student switches backends, model-only results from the previous
  // backend must not be displayed as if they came from the new one. Corrections
  // and sender rules are kept because they are explicit user choices. Any
  // in-flight classification responses are also discarded by bumping the run id.
  useEffect(() => {
    if (!backend) return;
    stopClassification();
    setEmails((previous) =>
      previous.map((email) => {
        const c = email.classification;
        if (!c || c.corrected || c.byRule || c.backend === backend) return email;
        return { ...email, classification: undefined, classifyError: undefined };
      }),
    );
  }, [backend, stopClassification]);


  const [windowDays, setWindowDaysState] = useState<WindowDays>(readWindow);
  const setWindowDays = (value: WindowDays) => {
    setWindowDaysState(value);
    writePref(WINDOW_KEY, String(value));
  };
  const [range, setRange] = useState<DateRange>({ since: "", before: "" });
  const bounds = useRef<{ since?: string; before?: string }>({});
  bounds.current = loadBounds(windowDays, range);
  const [query, setQuery] = useState("");
  const [action, setAction] = useState<ActionFilter>("all");
  const [categories, setCategories] = useState<readonly CategoryKey[]>([]);
  const [sort, setSortState] = useState<SortOrder>(
    readPref(SORT_KEY) === "oldest" ? "oldest" : "newest",
  );
  const setSort = (value: SortOrder) => {
    setSortState(value);
    writePref(SORT_KEY, value);
  };
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [detailFocusNonce, setDetailFocusNonce] = useState(0);

  /* ---- Backends and health ---- */

  useEffect(() => {
    const abort = new AbortController();

    fetchBackends(abort.signal)
      .then((data) => {
        setBackends(data.backends);
        setBackend((current) => current || data.default);
      })
      .catch(() => {
        // The page still works for loading; classification will report the error.
      });

    return () => abort.abort();
  }, []);

  useEffect(() => {
    if (!backend) {
      return;
    }

    const abort = new AbortController();
    setHealth(null);

    fetchHealth(backend, abort.signal)
      .then(setHealth)
      .catch(() => {});

    return () => abort.abort();
  }, [backend]);

  /* ---- Loading ---- */

  const load = useCallback(
    async (options: { announce?: boolean } = {}) => {
      if (session.provider === "outlook" && !token.trim()) {
        setTokenDialogOpen(true);
        setNotice({ text: "Paste a Graph access token first.", error: true });
        return;
      }

      setPaused(false);
      // A fresh load supersedes any in-flight load or classification: the old
      // targets and results are no longer relevant.
      loadController.current?.abort();
      stopClassification();
      const abort = new AbortController();
      loadController.current = abort;
      loading.current = true;
      setPhase("loading");
      setNotice(null);
      setProgress(null);

      try {
        const result = await fetchEmails(
          {
            provider: session.provider,
            token: token.trim(),
            count: Math.min(DEFAULT_COUNT, session.maxEmails || DEFAULT_COUNT),
            backend: backendRef.current || undefined,
            ...bounds.current,
          },
          abort.signal,
        );

        // A newer load, a cancel or a refresh owns the state now: drop this response.
        if (abort.signal.aborted || loadController.current !== abort) {
          return;
        }
        raw.current = new Map(result.raw.map((item) => [item.id, item]));
        setEmails((previous) => mergeEmails(previous, result.emails, backendRef.current));
        setSelectedId((current) =>
          result.emails.some((email) => email.id === current)
            ? current
            : (result.emails[0]?.id ?? null),
        );
        setPhase("ready");

        if (options.announce) {
          const count = result.emails.length;
          setNotice(
            count
              ? {
                  text: `Loaded ${count} email${count === 1 ? "" : "s"}. Sorting starts shortly.`,
                  error: false,
                }
              : {
                  text: isPushed
                    ? "No mail yet. New messages appear here after your flow sends them."
                    : "No emails found in your mailbox.",
                  error: false,
                },
          );
        }
      } catch (error) {
        if (isAbort(error) || abort.signal.aborted || loadController.current !== abort) {
          return;
        }
        setPhase(emails.length ? "ready" : "idle");
        const expired = session.provider === "outlook" && (error as { status?: number }).status === 401;
        setNotice({
          text: expired
            ? "Your Outlook token has expired. Paste a fresh one to keep going."
            : error instanceof Error
              ? error.message
              : "Could not load mail.",
          error: true,
        });
        if (expired) {
          setTokenDialogOpen(true);
        }
      } finally {
        if (loadController.current === abort) {
          loadController.current = null;
          loading.current = false;
        }
      }
    },
    [emails.length, isPushed, session.maxEmails, session.provider, setPaused, stopClassification, token],
  );

  // First load. Pushed mail needs no token; Outlook waits for the dialog.
  const started = useRef(false);
  useEffect(() => {
    if (started.current) {
      return;
    }
    started.current = true;

    if (isPushed) {
      void load();
      void fetchRefreshConfigured().then((configured) => {
        if (configured) {
          void requestFlowRefresh().catch(() => {});
        }
      });
    }
  }, [isPushed, load]);

  // A new time band means a new request. Skip the first render, which already loads.
  const bandKey = `${windowDays}|${range.since}|${range.before}`;
  const lastBand = useRef(bandKey);
  const latestLoad = useRef(load);
  latestLoad.current = load;
  useEffect(() => {
    if (lastBand.current === bandKey) {
      return;
    }
    lastBand.current = bandKey;
    if (!started.current || (session.provider === "outlook" && !token.trim())) {
      return;
    }
    const timer = window.setTimeout(() => void latestLoad.current(), 300);
    return () => window.clearTimeout(timer);
  }, [bandKey, session.provider, token]);

  // Pushed mail arrives on its own, so poll quietly while the tab is visible.
  useEffect(() => {
    if (!isPushed) {
      return;
    }

    const timer = window.setInterval(async () => {
      if (loading.current || classifying.current || document.visibilityState === "hidden") {
        return;
      }

      const abort = new AbortController();
      loadController.current = abort;
      loading.current = true;
      try {
        const result = await fetchEmails(
          {
            provider: session.provider,
            token: "",
            count: Math.min(DEFAULT_COUNT, session.maxEmails || DEFAULT_COUNT),
            backend: backendRef.current || undefined,
            ...bounds.current,
          },
          abort.signal,
        );
        if (abort.signal.aborted || loadController.current !== abort) {
          return;
        }
        raw.current = new Map(result.raw.map((item) => [item.id, item]));
        setEmails((previous) => mergeEmails(previous, result.emails, backendRef.current));
        setPhase("ready");
        setSelectedId((current) => current ?? result.emails[0]?.id ?? null);
      } catch {
        // Offline or idle; the next tick retries.
      } finally {
        if (loadController.current === abort) {
          loadController.current = null;
          loading.current = false;
        }
      }
    }, PUSH_POLL_MS);

    return () => window.clearInterval(timer);
  }, [isPushed, session.maxEmails, session.provider]);

  /* ---- Classification ---- */

  const windowed = useMemo(
    () => withinWindow(emails, windowDays, range),
    [emails, windowDays, range],
  );

  const runClassification = useCallback(
    async (targets: readonly InboxEmail[], quiet: boolean) => {
      if (!targets.length) {
        if (!quiet) {
          setNotice({
            text: "No emails in this time window. Choose a longer window or load mail first.",
            error: true,
          });
        }
        return;
      }

      const runId = (classifyRun.current += 1);
      classifyController.current?.abort();
      const abort = new AbortController();
      classifyController.current = abort;
      classifying.current = true;
      setNotice(null);
      setAutoRun(quiet);
      setProgress({ done: 0, total: targets.length });

      let failures = 0;
      const startedBackend = backendRef.current;

      try {
        // Worker pool: Claude calls mostly wait on the network, so run several at once.
        let nextIndex = 0;
        let completed = 0;
        const superseded = () => abort.signal.aborted || runId !== classifyRun.current;

        const worker = async () => {
          while (!superseded()) {
            const index = nextIndex;
            nextIndex += 1;
            if (index >= targets.length) {
              return;
            }

            const id = targets[index].id;
            const source = raw.current.get(id);

            try {
              if (!source) {
                throw new Error("Email is no longer loaded.");
              }
              const classification = await classifyEmail(source, backend, abort.signal);
              // Ignore results that belong to a superseded run or a backend switch.
              if (superseded()) {
                return;
              }
              const tagged = { ...classification, backend: startedBackend };
              setEmails((previous) =>
                previous.map((email) =>
                  email.id === id
                    ? { ...email, classification: tagged, classifyError: undefined }
                    : email,
                ),
              );
            } catch (error) {
              if (superseded()) {
                return;
              }
              failures += 1;
              const message =
                error instanceof Error ? error.message : "Classification failed.";
              setEmails((previous) =>
                previous.map((email) =>
                  email.id === id
                    ? { ...email, classification: undefined, classifyError: message }
                    : email,
                ),
              );
            }

            completed += 1;
            setProgress({ done: completed, total: targets.length });
          }
        };

        await Promise.all(
          Array.from({ length: Math.min(CLASSIFY_CONCURRENCY, targets.length) }, worker),
        );

        if (runId !== classifyRun.current) {
          // A newer run or a backend switch is in charge; do not overwrite its notice.
        } else if (abort.signal.aborted) {
          setNotice({ text: "Sorting stopped.", error: false });
        } else if (failures) {
          setNotice({
            text: `${failures} email${failures === 1 ? "" : "s"} could not be sorted.`,
            error: true,
          });
        } else if (!quiet) {
          setNotice({
            text: `Sorted ${targets.length} email${targets.length === 1 ? "" : "s"}.`,
            error: false,
          });
        }
      } finally {
        // Only the most recent classification run may tear down the busy/progress state.
        if (classifyRun.current === runId) {
          classifyController.current = null;
          classifying.current = false;
          setProgress(null);
          setAutoRun(false);
        }
      }
    },
    [backend],
  );

  /** Manual: sort everything in the window again. */
  const classifyAll = useCallback(async () => {
    setPaused(false);
    await runClassification(windowed, false);
  }, [runClassification, setPaused, windowed]);

  const pending = useMemo(
    () => windowed.filter((email) => !email.classification && !email.classifyError),
    [windowed],
  );

  const failed = useMemo(
    () => windowed.filter((email) => !!email.classifyError),
    [windowed],
  );

  /** Manual: sort only what is not sorted yet. */
  const classifyPending = useCallback(async () => {
    setPaused(false);
    await runClassification(pending, false);
  }, [pending, runClassification, setPaused]);

  /** Manual: retry only emails that failed in the selected window. */
  const retryFailed = useCallback(async () => {
    setPaused(false);
    await runClassification(failed, false);
  }, [failed, runClassification, setPaused]);

  // Auto-sort: new or newly visible mail is sorted in the background. Results
  // are cached on the server, so an email reaches the model only once.
  const sorting = progress !== null;

  // Pushed mail: has anything arrived in the last quiet spell?
  const [quiet, setQuiet] = useState(false);
  useEffect(() => {
    setQuiet(false);
    if (!isPushed) {
      return;
    }
    const timer = window.setTimeout(() => setQuiet(true), PUSH_SORT_QUIET_MS);
    return () => window.clearTimeout(timer);
  }, [isPushed, emails.length]);

  // Pushed mail is still coming in: the count grew a moment ago. Used to keep the
  // screen to a plain "loading" message until the flow has finished sending.
  const [receiving, setReceiving] = useState(false);
  const lastCount = useRef(0);
  useEffect(() => {
    const previous = lastCount.current;
    lastCount.current = emails.length;
    // The first batch is the baseline, not "arriving".
    if (!isPushed || previous === 0 || emails.length <= previous) {
      return;
    }
    setReceiving(true);
    const timer = window.setTimeout(() => setReceiving(false), PUSH_ARRIVAL_QUIET_MS);
    return () => window.clearTimeout(timer);
  }, [isPushed, emails.length]);

  const waitingForBatch = isPushed && pending.length > 0 && pending.length < PUSH_SORT_BATCH && !quiet;

  useEffect(() => {
    if (
      waitingForBatch ||
      !autoSort ||
      paused.current ||
      phase !== "ready" ||
      sorting ||
      !backend ||
      health?.ready === false ||
      pending.length === 0
    ) {
      return;
    }

    void runClassification(pending, true);
  }, [autoSort, backend, health, pending, phase, runClassification, sorting, waitingForBatch]);

  function setAutoSort(value: boolean) {
    setAutoSortState(value);
    setPaused(false);
    try {
      window.localStorage.setItem(AUTO_SORT_KEY, value ? "on" : "off");
    } catch {
      // The setting simply will not persist.
    }
  }

  /* ---- Corrections ---- */

  const correct = useCallback(
    async (
      id: string,
      category: CategoryKey,
      action: ActionKey,
      rememberSender = false,
    ) => {
      const email = emails.find((item) => item.id === id);
      const source = raw.current.get(id);

      if (!email || !source) {
        throw new Error("Email is no longer loaded.");
      }

      const before = email.classification;
      const original =
        before?.original ??
        (before
          ? { category: before.category, action: before.action }
          : { category: "others" as const, action: "no_immediate_action" as const });

      await saveCorrection(source, backend, original, category, action, rememberSender);
      const address = senderKey(email.sender);

      setEmails((previous) =>
        previous.map((item) => {
          if (item.id === id) {
            return {
              ...item,
              classifyError: undefined,
              classification: {
                category,
                action,
                reason: "Corrected by you.",
                corrected: true,
                original,
                backend,
              },
            };
          }
          // A new rule also applies to mail already on screen from that sender,
          // unless the student fixed that email by hand.
          if (
            rememberSender &&
            address &&
            senderKey(item.sender) === address &&
            !item.classification?.corrected
          ) {
            return {
              ...item,
              classifyError: undefined,
              classification: {
                category,
                action,
                reason: "Your rule for this sender.",
                byRule: true,
                backend,
              },
            };
          }
          return item;
        }),
      );
    },
    [backend, emails],
  );

  /** Remove a sender rule; its mail goes back to the sorter. */
  const removeRule = useCallback(
    async (id: string) => {
      const email = emails.find((item) => item.id === id);
      const address = email ? senderKey(email.sender) : "";

      if (!address) {
        throw new Error("This email has no sender address.");
      }

      await deleteSenderRule(address);
      setEmails((previous) =>
        previous.map((item) =>
          senderKey(item.sender) === address && item.classification?.byRule
            ? { ...item, classification: undefined }
            : item,
        ),
      );
    },
    [emails],
  );

  const undoCorrection = useCallback(
    async (id: string) => {
      const source = raw.current.get(id);

      if (!source) {
        throw new Error("Email is no longer loaded.");
      }

      await deleteCorrection(id);
      // The server still has the model's answer cached, so this is instant.
      const classification = await classifyEmail(source, backend);
      const tagged = { ...classification, backend };
      setEmails((previous) =>
        previous.map((item) =>
          item.id === id ? { ...item, classification: tagged, classifyError: undefined } : item,
        ),
      );
    },
    [backend],
  );

  const draftReply = useCallback(
    async (id: string, signal?: AbortSignal) => {
      const source = raw.current.get(id);

      if (!source) {
        throw new Error("Email is no longer loaded.");
      }

      return requestDraftReply(source, signal);
    },
    [],
  );

  const sendReply = useCallback(
    async (id: string, reply: string, token?: string) => {
      const source = raw.current.get(id);

      if (!source) {
        throw new Error("Email is no longer loaded.");
      }

      await requestSendReply(source, reply, token);
    },
    [],
  );

  const cancel = useCallback(() => {
    setPaused(true);
    loadController.current?.abort();
    loadController.current = null;
    loading.current = false;
    classifyController.current?.abort();
    classifyController.current = null;
    classifying.current = false;
    setProgress(null);
    setAutoRun(false);
    setPhase((current) => (current === "loading" ? (emails.length ? "ready" : "idle") : current));
  }, [emails.length, setPaused]);

  useEffect(
    () => () => {
      loadController.current?.abort();
      classifyController.current?.abort();
    },
    [],
  );

  /* ---- Derived view ---- */

  const visibleEmails = useMemo(
    () => sortEmails(filterEmails(windowed, { query, action, categories }), sort),
    [windowed, query, action, categories, sort],
  );

  const counts = useMemo(() => countByAction(windowed), [windowed]);

  const selectedEmail = useMemo(
    () => visibleEmails.find((email) => email.id === selectedId) ?? null,
    [visibleEmails, selectedId],
  );

  const hasActiveFilters =
    query.trim() !== "" || action !== "all" || categories.length > 0;

  const classifiedCount = useMemo(
    () => windowed.filter((email) => email.classification).length,
    [windowed],
  );

  /* ---- Actions ---- */

  function toggleCategory(key: CategoryKey) {
    setCategories((current) =>
      current.includes(key)
        ? current.filter((item) => item !== key)
        : [...current, key],
    );
  }

  function clearFilters() {
    setQuery("");
    setAction("all");
    setCategories([]);
  }

  function selectEmail(id: string) {
    setSelectedId(id);

    if (!isDesktop()) {
      setMobileDetailOpen(true);
    }
  }

  /** Used by the calendar: clear filters so the source email is visible. */
  function openEmail(id: string) {
    clearFilters();
    setSelectedId(id);
    setDetailFocusNonce((current) => current + 1);

    if (!isDesktop()) {
      setMobileDetailOpen(true);
    }
  }

  /** Keyboard: step through the visible list without opening mobile detail. */
  function moveSelection(delta: 1 | -1) {
    if (!visibleEmails.length) {
      return;
    }
    const index = visibleEmails.findIndex((email) => email.id === selectedId);
    const next = Math.min(
      visibleEmails.length - 1,
      Math.max(0, index === -1 ? 0 : index + delta),
    );
    setSelectedId(visibleEmails[next].id);
  }

  function closeMobileDetail() {
    setMobileDetailOpen(false);
  }

  function submitToken(value: string) {
    setToken(value);
    setTokenDialogOpen(false);
  }

  // Load right after the token is saved.
  const lastLoadedToken = useRef("");
  useEffect(() => {
    if (session.provider === "outlook" && token.trim() && token !== lastLoadedToken.current) {
      lastLoadedToken.current = token;
      void load({ announce: true });
    }
  }, [load, session.provider, token]);

  return {
    session,
    emails,
    phase,
    loading: phase === "loading",
    classifying: progress !== null,
    progress,
    notice,
    dismissNotice: () => setNotice(null),
    load,
    classifyAll,
    classifyPending,
    retryFailed,
    pendingCount: pending.length,
    failedCount: failed.length,
    autoSort,
    waitingForBatch,
    receiving,
    sortBatchSize: PUSH_SORT_BATCH,
    setAutoSort,
    autoPaused,
    autoRun,
    correct,
    removeRule,
    undoCorrection,
    draftReply,
    sendReply,
    cancel,
    hasLoaded: emails.length > 0,
    classifiedCount,
    token,
    tokenDialogOpen,
    openTokenDialog: () => setTokenDialogOpen(true),
    closeTokenDialog: () => setTokenDialogOpen(false),
    submitToken,
    backends,
    backend,
    setBackend,
    health,
    windowDays,
    setWindowDays,
    range,
    setRange,
    rangeInvalid:
      windowDays === "custom" &&
      range.since !== "" &&
      range.before !== "" &&
      range.since > range.before,
    counts,
    query,
    setQuery,
    action,
    setAction,
    categories,
    toggleCategory,
    sort,
    setSort,
    selectedId,
    selectedEmail,
    visibleEmails,
    hasActiveFilters,
    clearFilters,
    selectEmail,
    moveSelection,
    openEmail,
    mobileDetailOpen,
    detailFocusNonce,
    closeMobileDetail,
    total: windowed.length,
    visibleCount: visibleEmails.length,
  };
}

export type InboxView = ReturnType<typeof useInboxView>;
