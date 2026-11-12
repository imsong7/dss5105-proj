import {
  Check,
  ChevronDown,
  Download,
  ExternalLink,
  Loader2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  FLOW_PACKAGE_URL,
  fetchSetup,
  requestFlowRefresh,
  saveFlowUrl,
} from "../services/flask";
import type { SetupInfo } from "../services/flask";
import { CopyBlock, CopyField } from "./CopyField";

const NEW_MAIL_BODY = `{
  "internetMessageId": "@{triggerOutputs()?['body/internetMessageId']}",
  "subject": "@{triggerOutputs()?['body/subject']}",
  "from": "@{triggerOutputs()?['body/from']}",
  "receivedDateTime": "@{triggerOutputs()?['body/receivedDateTime']}",
  "bodyPreview": "@{triggerOutputs()?['body/bodyPreview']}",
  "body": "@{triggerOutputs()?['body/body']}"
}`;

const OLD_MAIL_BODY = `{
  "internetMessageId": "@{item()?['internetMessageId']}",
  "subject": "@{item()?['subject']}",
  "from": "@{item()?['from']}",
  "receivedDateTime": "@{item()?['receivedDateTime']}",
  "bodyPreview": "@{item()?['bodyPreview']}",
  "body": "@{item()?['body']}"
}`;

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden="true"
        className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent"
      >
        {n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
        {children}
      </div>
    </li>
  );
}

const TEXT = "text-[14px] leading-5 text-muted";

function Setting({
  name,
  children,
}: {
  name: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-[13px] font-medium text-ink">{name}</p>
      {children}
    </div>
  );
}

/** Saves the imported flow's trigger URL, then asks the flow for mail once. */
function FlowUrlForm({
  saved,
  onSaved,
}: {
  saved: boolean;
  onSaved: () => void;
}) {
  const [url, setUrl] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">(
    saved ? "saved" : "idle",
  );
  const [message, setMessage] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!url.trim()) {
      return;
    }
    setState("saving");
    try {
      await saveFlowUrl(url.trim());
      setUrl("");
      setState("saved");
      setMessage("Saved. Asking your flow for mail…");
      const reached = await requestFlowRefresh().then(
        () => true,
        () => false,
      );
      setMessage(
        reached
          ? "Saved. Your mail is on its way."
          : "Saved, but the flow didn't answer. Make sure it's turned on, then press Check now.",
      );
      if (reached) {
        window.setTimeout(onSaved, 4000);
      }
    } catch (cause) {
      setState("error");
      setMessage(
        cause instanceof Error ? cause.message : "Could not save the address.",
      );
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor="flow-url" className="text-[13px] font-medium text-ink">
        HTTP URL{" "}
        {state === "saved" && !message ? (
          <span className="font-normal text-muted">
            (saved, paste again to change)
          </span>
        ) : null}
      </label>
      <div className="flex gap-2">
        <input
          id="flow-url"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://…logic.azure.com/workflows/…"
          className="min-h-11 min-w-0 flex-1 rounded-[10px] border border-line bg-surface px-3 text-[14px] text-ink placeholder:text-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        />
        <button
          type="submit"
          disabled={state === "saving" || !url.trim()}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          {state === "saving" ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : null}
          Save
        </button>
      </div>
      {message ? (
        <p
          role={state === "error" ? "alert" : "status"}
          className={`flex items-center gap-1.5 text-[13px] ${state === "error" ? "text-action-now-fg" : "text-muted"}`}
        >
          {state === "saved" ? (
            <Check className="h-4 w-4 text-accent" aria-hidden="true" />
          ) : null}
          {message}
        </p>
      ) : null}
    </form>
  );
}

/** Step-by-step Power Automate setup with this account's own values filled in. */
export function SetupGuide({
  open,
  onClose,
  received,
  onCheck,
  onSwitchSource,
}: {
  open: boolean;
  onClose: () => void;
  /** How many emails the app has so far. */
  received: number;
  onCheck: () => void;
  /** Present when the student may use an Outlook token instead. */
  onSwitchSource?: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [info, setInfo] = useState<SetupInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) {
      return;
    }
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    if (!open || info) {
      return;
    }
    const abort = new AbortController();
    fetchSetup(abort.signal)
      .then(setInfo)
      .catch((cause: unknown) => {
        if (!abort.signal.aborted) {
          setError(
            cause instanceof Error && /404/.test(cause.message)
              ? "Setup details aren't available. Restart the app and open this guide again."
              : cause instanceof Error
                ? cause.message
                : "Could not load your settings.",
          );
        }
      });
    return () => abort.abort();
  }, [open, info]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="setup-title"
      className="m-auto max-h-[90dvh] w-[min(600px,calc(100%-32px))] overflow-y-auto rounded-2xl border border-line bg-surface p-0 text-ink shadow-[0_24px_60px_rgba(0,0,0,0.25)] backdrop:bg-black/40"
    >
      <div className="p-5">
        <h2 id="setup-title" className="text-[17px] font-semibold">
          Connect your Outlook
        </h2>
        <p className={`mt-1 ${TEXT}`}>
          About 5 minutes, once. A small flow in your Microsoft account sends your
          mail here.
        </p>
        <p className="mt-2 rounded-lg bg-highlight-soft px-3 py-2 text-[13px] leading-5 text-highlight-dark">
          Needs Power Automate's premium <strong>HTTP</strong> action. If you see
          a diamond or a licence prompt, check with IT first.
        </p>
        {onSwitchSource ? (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg border border-line px-3 py-2">
            <p className="text-[13px] leading-5 text-muted">
              No licence? Use an Outlook token: works now, lasts about an hour.
            </p>
            <button
              type="button"
              onClick={onSwitchSource}
              className="min-h-11 shrink-0 rounded-[10px] px-2 text-[13px] font-semibold text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              Use a token instead
            </button>
          </div>
        ) : null}

        {error ? (
          <p role="alert" className="mt-4 text-[14px] text-action-now-fg">
            {error}
          </p>
        ) : !info ? (
          <p
            role="status"
            className="mt-4 flex items-center gap-2 text-[13px] text-muted"
          >
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading your settings…
          </p>
        ) : (
          <>
            <ol className="mt-5 flex flex-col gap-6">
              <Step n={1} title="Download your flow">
                <p className={TEXT}>
                  Already set up for your account. Don't share the file.{" "}
                  {info?.flow_sends_images
                    ? "It sends each email's text and one small image (for posters)."
                    : "It sends each email's text only (no images)."}
                </p>
                <a
                  href={FLOW_PACKAGE_URL}
                  download="nusbox-flow.zip"
                  className="inline-flex min-h-11 w-fit items-center gap-2 rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none"
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  Download my flow (.zip)
                </a>
              </Step>

              <Step n={2} title="Import it into Power Automate">
                <ol className={`list-decimal space-y-1 pl-5 ${TEXT}`}>
                  <li>
                    <strong>My flows</strong> → <strong>Import</strong> →{" "}
                    <strong>Import Package (Legacy)</strong>, and upload the .zip.
                  </li>
                  <li>
                    At <strong>Your Outlook connection</strong>, choose{" "}
                    <strong>Select during import</strong>, pick your account, then{" "}
                    <strong>Save</strong>.
                  </li>
                  <li>
                    Press <strong>Import</strong>, then turn the flow on.
                  </li>
                </ol>
                <a
                  href="https://make.powerautomate.com/manage/flows"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-11 w-fit items-center gap-1.5 rounded-lg px-1 text-[14px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                >
                  Open Power Automate
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                </a>
              </Step>

              <Step n={3} title="Paste the flow's address here">
                <p className={TEXT}>
                  Edit the flow, open <strong>When a HTTP request is received</strong>,
                  and copy its <strong>HTTP URL</strong>.
                </p>
                <FlowUrlForm
                  saved={Boolean(info.flow_url_saved)}
                  onSaved={onCheck}
                />
              </Step>

              <Step n={4} title="Check it works">
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={onCheck}
                    className="min-h-11 rounded-[10px] border border-line px-4 text-[14px] font-semibold text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                  >
                    Check now
                  </button>
                  <p role="status" className="text-[13px] text-muted">
                    {received > 0
                      ? `${received} email${received === 1 ? "" : "s"} received so far.`
                      : "No emails yet. The first run can take a minute or two."}
                  </p>
                </div>
              </Step>
            </ol>

            <details className="group mt-6 rounded-xl border border-line">
              <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 px-4 text-[14px] font-medium text-ink [&::-webkit-details-marker]:hidden">
                Prefer to build the flow by hand?
                <ChevronDown
                  className="h-4 w-4 text-muted transition-transform group-open:rotate-180"
                  aria-hidden="true"
                />
              </summary>
              <div className="border-t border-line px-4 pt-4 pb-5">
                <p className={`mb-4 ${TEXT}`}>
                  Sends each new email as soon as it arrives.
                </p>
                <ol className="flex flex-col gap-6">
                  <Step n={1} title="Create the flow">
                    <p className={TEXT}>
                      <strong>Create</strong> → <strong>Automated cloud flow</strong>,
                      trigger <strong>When a new email arrives (V3)</strong>.
                    </p>
                    <a
                      href="https://make.powerautomate.com"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex min-h-11 w-fit items-center gap-1.5 rounded-lg px-1 text-[14px] font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                    >
                      Open Power Automate
                      <ExternalLink
                        className="h-3.5 w-3.5"
                        aria-hidden="true"
                      />
                    </a>
                  </Step>

                  <Step n={2} title="Add an HTTP action">
                    <p className={TEXT}>
                      Add a step: <strong>HTTP</strong>. Fill in:
                    </p>
                    <Setting name="Method">
                      <CopyField value="POST" />
                    </Setting>
                    <Setting name="URI">
                      <CopyField value={info.endpoint} label="Copy address" />
                    </Setting>
                    <Setting name="Headers (add each as a key and value)">
                      <div className="flex flex-col gap-2">
                        <CopyField value="Content-Type: application/json" />
                        <CopyField value={`X-User-Email: ${info.email}`} />
                        <CopyField
                          value={`X-Webhook-Token: ${info.token}`}
                          label="Copy token line"
                          secret
                          openPrefix="X-Webhook-Token: "
                        />
                        <CopyField value="ngrok-skip-browser-warning: true" />
                      </div>
                    </Setting>
                    <p className="text-[13px] leading-5 text-muted">
                      Before the colon goes in <em>Key</em>, after it in{" "}
                      <em>Value</em>. Keep the token private.
                    </p>
                    <Setting name="Body">
                      <CopyBlock value={NEW_MAIL_BODY} label="Copy body" />
                    </Setting>
                  </Step>

                  <Step n={3} title="Save and test">
                    <p className={TEXT}>
                      Save, then send yourself an email. It shows up here in a minute or two.
                    </p>
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        onClick={onCheck}
                        className="min-h-11 rounded-[10px] border border-line px-4 text-[14px] font-semibold text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                      >
                        Check now
                      </button>
                      <p role="status" className="text-[13px] text-muted">
                        {received > 0
                          ? `${received} email${received === 1 ? "" : "s"} received so far.`
                          : "No emails yet."}
                      </p>
                    </div>
                  </Step>

                  <Step n={4} title="Bring in your older mail (optional)">
                    <p className={TEXT}>
                      A second flow: <strong>Manually trigger a flow</strong> →{" "}
                      <strong>Get emails (V3)</strong> (Inbox, Top 200) → the same HTTP
                      action with this body. Run it once with <strong>Test</strong>.
                    </p>
                    <CopyBlock value={OLD_MAIL_BODY} label="Copy body" />
                  </Step>
                </ol>
              </div>
            </details>
          </>
        )}

        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none"
          >
            Done
          </button>
        </div>
      </div>
    </dialog>
  );
}
