import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

const PHONE = "(max-width: 639px)";

/** True on phone-width screens, where menus and panels open as bottom sheets. */
export function usePhone(): boolean {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE).matches);

  useEffect(() => {
    const media = window.matchMedia(PHONE);
    const update = () => setPhone(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return phone;
}

/** A panel that slides up from the bottom. Rendered at the page root. */
export function BottomSheet({
  open,
  label,
  onClose,
  children,
  panelId,
}: {
  open: boolean;
  label: string;
  onClose: () => void;
  children: ReactNode;
  panelId?: string;
}) {
  useEffect(() => {
    if (!open) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return createPortal(
    <div className="fixed inset-0 z-[60]">
      <div aria-hidden="true" onClick={onClose} className="absolute inset-0 bg-black/35" />
      <div
        id={panelId}
        role="dialog"
        aria-label={label}
        className="sheet-in absolute inset-x-0 bottom-0 max-h-[80dvh] overflow-y-auto rounded-t-2xl bg-surface px-4 pt-2 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-[0_-12px_32px_rgba(0,0,0,0.18)]"
      >
        <span aria-hidden="true" className="mx-auto mb-2 block h-1 w-9 rounded-full bg-line" />
        {children}
      </div>
    </div>,
    document.body,
  );
}
