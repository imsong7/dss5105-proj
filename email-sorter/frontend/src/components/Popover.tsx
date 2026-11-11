import { useEffect, useId, useRef, useState } from "react";
import { BottomSheet, usePhone } from "./BottomSheet";
import type { ReactNode } from "react";

interface PopoverProps {
  label: ReactNode;
  ariaLabel: string;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: "left" | "right";
  buttonClassName?: string;
  active?: boolean;
}

export const FIELD_BUTTON =
  "inline-flex h-11 items-center gap-1.5 rounded-xl border bg-surface px-3 text-[13px] font-medium text-ink transition-colors sm:h-9 hover:bg-surface-muted/60 focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none";

/**
 * Small dropdown panel: closes on outside click or Escape. On a phone it opens
 * as a bottom sheet instead, rendered at the page root so no parent can clip it.
 */
export function Popover({
  label,
  ariaLabel,
  children,
  align = "left",
  buttonClassName = "",
  active = false,
}: PopoverProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const phone = usePhone();

  useEffect(() => {
    if (!open) {
      return;
    }

    function onPointerDown(event: MouseEvent) {
      if (root.current && !root.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    // On a phone the sheet's backdrop handles outside taps.
    if (!phone) {
      document.addEventListener("mousedown", onPointerDown);
    }
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, phone]);

  const content = typeof children === "function" ? children(() => setOpen(false)) : children;

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
        className={`${FIELD_BUTTON} ${
          active ? "border-accent/40 bg-accent-soft text-accent-dark" : "border-line"
        } ${buttonClassName}`}
      >
        {label}
      </button>
      <BottomSheet open={open && phone} label={ariaLabel} onClose={() => setOpen(false)} panelId={panelId}>
        {content}
      </BottomSheet>
      {open && !phone ? (
        <div
          id={panelId}
          className={`absolute top-[calc(100%+6px)] z-30 w-[min(280px,calc(100vw-32px))] rounded-2xl border border-line bg-surface p-3 shadow-[0_12px_32px_rgba(0,0,0,0.14)] ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          {content}
        </div>
      ) : null}
    </div>
  );
}
