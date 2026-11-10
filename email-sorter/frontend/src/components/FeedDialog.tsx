import { useEffect, useRef, useState } from "react";

import { fetchFeed, rotateFeed } from "../services/flask";
import type { FeedLinks } from "../services/flask";

export function FeedDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [links, setLinks] = useState<FeedLinks | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) {
      return;
    }

    if (open && !dialog.open) {
      setCopied(false);
      setConfirmReset(false);
      setError(null);
      dialog.showModal();
      fetchFeed()
        .then(setLinks)
        .catch((cause: unknown) =>
          setError(cause instanceof Error ? cause.message : "Could not create the link."),
        );
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  async function copy() {
    if (!links) {
      return;
    }
    try {
      await navigator.clipboard.writeText(links.url);
    } catch {
      // Clipboard can be blocked; selecting the text lets the student copy it.
      input.current?.select();
      document.execCommand("copy");
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  async function reset() {
    try {
      setLinks(await rotateFeed());
      setConfirmReset(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reset the link.");
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="feed-title"
      className="m-auto w-[min(460px,calc(100%-32px))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-[0_24px_60px_rgba(0,0,0,0.25)] backdrop:bg-black/40"
    >
      <div className="p-5">
        <h2 id="feed-title" className="text-[17px] font-semibold">
          Deadlines in your calendar app
        </h2>
        <p className="mt-1.5 text-[14px] leading-5 text-muted">
          Add this link once. Your deadlines and events then appear in Google or Apple Calendar,
          and the app does not need to be open.
        </p>

        {links ? (
          <>
            <label htmlFor="feed-url" className="mt-4 block text-[13px] font-medium">
              Your private link
            </label>
            <div className="mt-1.5 flex gap-2">
              <input
                id="feed-url"
                ref={input}
                readOnly
                value={links.url}
                onFocus={(event) => event.currentTarget.select()}
                className="h-11 min-w-0 flex-1 rounded-[10px] border border-line bg-surface-muted px-3 text-[13px] text-ink focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
              />
              <button
                type="button"
                onClick={() => void copy()}
                className="min-h-11 shrink-0 rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>

            <ul className="mt-3 flex flex-col gap-1 text-[13px] text-ink/85">
              <li>
                <strong className="font-semibold">Google:</strong> Other calendars → From URL →
                paste the link.
              </li>
              <li>
                <strong className="font-semibold">Apple:</strong>{" "}
                <a
                  href={links.webcal}
                  className="text-accent underline underline-offset-2"
                >
                  Add to Apple Calendar
                </a>
              </li>
            </ul>

            <p className="mt-3 text-[13px] leading-5 text-muted">
              Anyone with this link can see your deadline titles. Calendar apps refresh every few
              hours, and only while this app is online.
            </p>

            <div className="mt-3">
              {confirmReset ? (
                <span className="flex flex-wrap items-center gap-2 text-[13px]">
                  The old link will stop working.
                  <button
                    type="button"
                    onClick={() => void reset()}
                    className="min-h-11 rounded-lg px-2 font-semibold text-action-now-fg hover:bg-action-now-bg focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                  >
                    Reset now
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmReset(false)}
                    className="min-h-11 rounded-lg px-2 text-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                  >
                    Cancel
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmReset(true)}
                  className="min-h-11 rounded-lg px-1 text-[13px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                >
                  Reset link
                </button>
              )}
            </div>
          </>
        ) : error ? null : (
          <p className="mt-4 text-[14px] text-muted">Creating your link…</p>
        )}

        {error ? (
          <p role="alert" className="mt-3 text-[13px] text-action-now-fg">
            {error}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 rounded-[10px] px-4 text-[14px] font-medium text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          >
            Close
          </button>
        </div>
      </div>
    </dialog>
  );
}
