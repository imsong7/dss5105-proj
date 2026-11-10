import { useCallback, useEffect, useRef, useState } from "react";

export interface ToastInput {
  text: string;
  actionLabel?: string;
  onAction?: () => void;
  /** Milliseconds before it disappears. Toasts with an action stay longer. */
  durationMs?: number;
}

interface Toast extends ToastInput {
  id: number;
}

/** Queue of short messages with an optional Undo. Render `node` once. */
export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (input: ToastInput) => {
      const id = next.current++;
      setToasts((current) => [...current.slice(-2), { ...input, id }]);
      timers.current.set(
        id,
        window.setTimeout(() => dismiss(id), input.durationMs ?? (input.onAction ? 6000 : 3500)),
      );
    },
    [dismiss],
  );

  useEffect(() => {
    const active = timers.current;
    return () => active.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const node = (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-50 sm:bottom-4 flex flex-col items-center gap-2 px-4"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="toast-enter pointer-events-auto relative flex min-h-11 overflow-hidden items-center gap-3 rounded-xl bg-[var(--toast-bg)] py-1 pr-1 pl-4 text-[14px] text-[var(--toast-fg)] shadow-[0_8px_24px_rgba(0,0,0,0.25)]"
        >
          <span>{toast.text}</span>
          {toast.onAction ? (
            <button
              type="button"
              onClick={() => {
                toast.onAction?.();
                dismiss(toast.id);
              }}
              className="min-h-11 rounded-lg px-3 font-semibold text-[var(--toast-link)] hover:bg-black/10 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              {toast.actionLabel ?? "Undo"}
            </button>
          ) : (
            <span className="w-3" />
          )}
          <span
            aria-hidden="true"
            className="absolute inset-x-0 bottom-0 h-0.5 origin-left bg-current opacity-30"
            style={{
              animation: `toast-timer ${toast.durationMs ?? (toast.onAction ? 6000 : 3500)}ms linear forwards`,
            }}
          />
        </div>
      ))}
    </div>
  );

  return { push, node };
}

export type Toasts = ReturnType<typeof useToasts>;
