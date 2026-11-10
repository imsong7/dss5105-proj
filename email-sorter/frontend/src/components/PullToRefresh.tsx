import { ArrowDown, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const TRIGGER_PX = 64;
const MAX_PX = 96;

/**
 * Phones: drag down from the top of the page to reload mail. Only starts when
 * the page is already scrolled to the top and no sheet or dialog is open.
 */
export function PullToRefresh({
  enabled,
  busy,
  onRefresh,
}: {
  enabled: boolean;
  busy: boolean;
  onRefresh: () => void;
}) {
  const [pull, setPull] = useState(0);
  // Show the spinner only for a reload the student pulled for.
  const [pulled, setPulled] = useState(false);
  useEffect(() => {
    if (!busy) {
      setPulled(false);
    }
  }, [busy]);
  const start = useRef<number | null>(null);
  const latest = useRef({ pull: 0, onRefresh, busy });
  latest.current = { pull, onRefresh, busy };

  useEffect(() => {
    if (!enabled) {
      return;
    }

    function blocked() {
      return (
        window.scrollY > 0 ||
        document.querySelector("dialog[open]") !== null ||
        document.querySelector('[role="dialog"]') !== null
      );
    }

    function onStart(event: TouchEvent) {
      start.current = blocked() || latest.current.busy ? null : event.touches[0].clientY;
    }

    function onMove(event: TouchEvent) {
      if (start.current === null) {
        return;
      }
      const distance = event.touches[0].clientY - start.current;
      setPull(distance > 0 ? Math.min(MAX_PX, distance * 0.5) : 0);
    }

    function onEnd() {
      if (start.current !== null && latest.current.pull >= TRIGGER_PX) {
        setPulled(true);
        latest.current.onRefresh();
      }
      start.current = null;
      setPull(0);
    }

    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onEnd);
    window.addEventListener("touchcancel", onEnd);
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("touchcancel", onEnd);
    };
  }, [enabled]);

  const spinning = pulled && busy;
  if (!enabled || (pull === 0 && !spinning)) {
    return null;
  }

  const ready = pull >= TRIGGER_PX;

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-x-0 top-0 z-40 flex justify-center sm:hidden"
      style={{ transform: `translateY(${spinning ? 24 : Math.max(0, pull - 28)}px)`, transition: pull ? undefined : "transform 0.2s ease" }}
    >
      <span className="mt-[env(safe-area-inset-top)] grid h-9 w-9 place-items-center rounded-full bg-surface text-accent shadow-[0_4px_14px_rgba(0,0,0,0.18)]">
        {spinning ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ArrowDown className={`h-4 w-4 transition-transform ${ready ? "rotate-180" : ""}`} />
        )}
      </span>
    </div>
  );
}
