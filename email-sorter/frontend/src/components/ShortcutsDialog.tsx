import { useEffect, useRef } from "react";

export const SHORTCUTS: readonly { keys: string; action: string }[] = [
  { keys: "g then t", action: "Go to Today" },
  { keys: "g then i", action: "Go to Inbox" },
  { keys: "g then c", action: "Go to Calendar" },
  { keys: "/", action: "Search your mail" },
  { keys: "j / k", action: "Next / previous email" },
  { keys: "e", action: "Mark the selected email handled" },
  { keys: "Ctrl / ⌘ K", action: "Jump to anything" },
  { keys: "?", action: "Show this list" },
];

export function ShortcutsDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

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

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="shortcuts-title"
      className="m-auto w-[min(380px,calc(100%-32px))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-[0_24px_60px_rgba(0,0,0,0.25)] backdrop:bg-black/40"
    >
      <div className="p-5">
        <h2 id="shortcuts-title" className="text-[17px] font-semibold">
          Keyboard shortcuts
        </h2>
        <dl className="mt-3 flex flex-col gap-1.5">
          {SHORTCUTS.map((item) => (
            <div key={item.keys} className="flex items-center justify-between gap-3">
              <dt className="text-[14px] text-ink">{item.action}</dt>
              <dd>
                <kbd className="rounded-md border border-line bg-surface-muted px-2 py-0.5 font-mono text-[12px] text-ink">
                  {item.keys}
                </kbd>
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 rounded-[10px] bg-accent px-4 text-[14px] font-semibold text-white hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:outline-none"
          >
            Got it
          </button>
        </div>
      </div>
    </dialog>
  );
}
