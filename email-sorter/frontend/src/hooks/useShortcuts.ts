import { useEffect, useRef } from "react";

interface ShortcutHandlers {
  goTo: (view: "today" | "inbox" | "calendar") => void;
  focusSearch: () => void;
  move: (delta: 1 | -1) => void;
  toggleHandled: () => void;
  showHelp: () => void;
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

/** Single-key shortcuts, ignored while typing or when a dialog is open. */
export function useShortcuts(handlers: ShortcutHandlers) {
  const latest = useRef(handlers);
  latest.current = handlers;

  useEffect(() => {
    let sequence: number | null = null;

    function clearSequence() {
      if (sequence !== null) {
        window.clearTimeout(sequence);
        sequence = null;
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        isTyping(event.target) ||
        document.querySelector("dialog[open]")
      ) {
        return;
      }

      const handlers = latest.current;

      if (sequence !== null) {
        clearSequence();
        const view = { t: "today", i: "inbox", c: "calendar" }[event.key] as
          | "today"
          | "inbox"
          | "calendar"
          | undefined;
        if (view) {
          event.preventDefault();
          handlers.goTo(view);
        }
        return;
      }

      switch (event.key) {
        case "g":
          sequence = window.setTimeout(clearSequence, 900);
          break;
        case "/":
          event.preventDefault();
          handlers.focusSearch();
          break;
        case "j":
          handlers.move(1);
          break;
        case "k":
          handlers.move(-1);
          break;
        case "e":
          handlers.toggleHandled();
          break;
        case "?":
          event.preventDefault();
          handlers.showHelp();
          break;
        default:
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      clearSequence();
    };
  }, []);
}
