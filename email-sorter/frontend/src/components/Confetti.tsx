import { useMemo } from "react";

const COLORS = ["#003d7c", "#ef7c00", "#f7a24b", "#3d86dc", "#12b76a"];

/** A short shower of paper pieces. Decorative; the reduced-motion rule hides the motion. */
export function Confetti() {
  const pieces = useMemo(
    () =>
      Array.from({ length: 34 }, (_, index) => ({
        id: index,
        left: Math.random() * 100,
        delay: Math.random() * 0.35,
        duration: 1.3 + Math.random() * 0.9,
        drift: (Math.random() - 0.5) * 120,
        spin: 360 + Math.random() * 540,
        color: COLORS[index % COLORS.length],
        size: 6 + Math.random() * 5,
      })),
    [],
  );

  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-[70] overflow-hidden">
      {pieces.map((piece) => (
        <i
          key={piece.id}
          className="confetti-piece"
          style={{
            left: `${piece.left}%`,
            width: piece.size,
            height: piece.size * 0.55,
            background: piece.color,
            animationDelay: `${piece.delay}s`,
            animationDuration: `${piece.duration}s`,
            ["--drift" as string]: `${piece.drift}px`,
            ["--spin" as string]: `${piece.spin}deg`,
          }}
        />
      ))}
    </div>
  );
}
