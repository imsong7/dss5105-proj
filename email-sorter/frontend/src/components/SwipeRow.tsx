import { useRef, useState } from "react";
import type { ReactNode } from "react";

interface SwipeRowProps {
  children: ReactNode;
  /** Swipe right. Leave out to disable that direction. */
  onSwipeRight?: () => void;
  rightLabel?: string;
  /** Swipe left. */
  onSwipeLeft?: () => void;
  leftLabel?: string;
  className?: string;
  /** Corner rounding of the clipped frame. */
  frameClassName?: string;
}

const COMMIT_PX = 88;
const LOCK_PX = 10;

/**
 * Touch-only swipe actions. Mouse and keyboard users keep the normal buttons,
 * so this never replaces an action, it only adds a shortcut on phones.
 */
export function SwipeRow({
  children,
  onSwipeRight,
  rightLabel = "Done",
  onSwipeLeft,
  leftLabel = "Snooze",
  className = "",
  frameClassName = "rounded-[10px]",
}: SwipeRowProps) {
  const [offset, setOffset] = useState(0);
  const [settling, setSettling] = useState(false);
  const start = useRef<{ x: number; y: number; id: number } | null>(null);
  const locked = useRef<"x" | "y" | null>(null);
  const moved = useRef(false);

  if (!onSwipeRight && !onSwipeLeft) {
    return <div className={className}>{children}</div>;
  }

  function clamp(dx: number): number {
    if (dx > 0 && !onSwipeRight) return 0;
    if (dx < 0 && !onSwipeLeft) return 0;
    return Math.max(-160, Math.min(160, dx));
  }

  function finish(commit: "right" | "left" | null) {
    start.current = null;
    locked.current = null;
    setSettling(true);

    if (commit) {
      // Slide the row out, then act while it is out of sight.
      setOffset(commit === "right" ? 420 : -420);
      window.setTimeout(() => {
        (commit === "right" ? onSwipeRight : onSwipeLeft)?.();
        setSettling(false);
        setOffset(0);
      }, 180);
    } else {
      setOffset(0);
      window.setTimeout(() => setSettling(false), 200);
    }
  }

  const revealRight = offset > 0;
  const armed = Math.abs(offset) >= COMMIT_PX;

  return (
    <div
      className={`relative overflow-hidden ${frameClassName}`}
      onClickCapture={(event) => {
        // A drag must not also count as a tap on the row underneath.
        if (moved.current) {
          event.stopPropagation();
          event.preventDefault();
          moved.current = false;
        }
      }}
    >
      {offset !== 0 ? (
        <div
          aria-hidden="true"
          className={`absolute inset-0 flex items-center px-5 text-[13px] font-semibold transition-colors ${
            revealRight
              ? `justify-start ${armed ? "bg-accent text-white" : "bg-accent-soft text-accent"}`
              : `justify-end ${armed ? "bg-highlight text-black" : "bg-highlight-soft text-highlight-dark"}`
          }`}
        >
          {revealRight ? rightLabel : leftLabel}
        </div>
      ) : null}
      <div
        className={`relative bg-surface ${className}`}
        style={{
          transform: offset ? `translateX(${offset}px)` : undefined,
          transition: settling ? "transform 0.18s ease-out" : undefined,
          touchAction: "pan-y",
        }}
        onPointerDown={(event) => {
          if (event.pointerType !== "touch") return;
          start.current = { x: event.clientX, y: event.clientY, id: event.pointerId };
          locked.current = null;
          moved.current = false;
          setSettling(false);
        }}
        onPointerMove={(event) => {
          const origin = start.current;
          if (!origin || event.pointerId !== origin.id) return;

          const dx = event.clientX - origin.x;
          const dy = event.clientY - origin.y;

          if (!locked.current) {
            if (Math.abs(dx) < LOCK_PX && Math.abs(dy) < LOCK_PX) return;
            locked.current = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
          }
          if (locked.current === "x") {
            moved.current = true;
            setOffset(clamp(dx));
          }
        }}
        onPointerUp={() => {
          if (!start.current) return;
          if (locked.current === "x") {
            finish(offset >= COMMIT_PX ? "right" : offset <= -COMMIT_PX ? "left" : null);
          } else {
            start.current = null;
          }
        }}
        onPointerCancel={() => {
          if (start.current && locked.current === "x") finish(null);
          start.current = null;
        }}
      >
        {children}
      </div>
    </div>
  );
}
