import { LION_BODY, LION_HAPPY_EYES, LION_HAPPY_MOUTH } from "./lionArt";

/**
 * The app's own mascot: an original cartoon lion lying down, with a shaggy
 * red-orange mane and a tufted tail. It is not a copy of any existing
 * character, the NUS mascot or logo, so it does not imply an official NUS
 * product. public/favicon.svg and public/icon.svg use the head of the same
 * drawing; the sign-in templates use the whole lion.
 *
 * The face shows how the day is going: happy by default, worried when
 * something is overdue, cheering when everything is done, sleepy at night.
 * `size` is the height; the lion is 1.5 times as wide.
 */
export type Mood = "happy" | "worried" | "cheer" | "sleepy";

const INK = "#3B1D0E";
const BROW = "#8A3A16";
const line = { fill: "none", strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

function Face({ mood }: { mood: Mood }) {
  if (mood === "happy") {
    return <g dangerouslySetInnerHTML={{ __html: LION_HAPPY_EYES + LION_HAPPY_MOUTH }} />;
  }

  if (mood === "sleepy") {
    return (
      <>
        <path d="M32 28.6q2.6 2.2 5.2 0M42.8 28.6q2.6 2.2 5.2 0" stroke={INK} strokeWidth="1" {...line} />
        <path d="M40 36.7v1.3M38.4 39.6h3.2" stroke={INK} strokeWidth="0.85" {...line} />
        <text x="54" y="16" fontSize="7" fontWeight="700" fill="#5B9BF0" style={{ fontFamily: "sans-serif" }}>
          z
        </text>
      </>
    );
  }

  if (mood === "cheer") {
    return (
      <>
        <path d="M32 29.4q2.6 -3.2 5.2 0M42.8 29.4q2.6 -3.2 5.2 0" stroke={INK} strokeWidth="1.1" {...line} />
        <path d="M31.6 23.6q3 -2.4 5.8 -.6M48.4 23.6q-3 -2.4 -5.8 -.6" stroke={BROW} strokeWidth="1" {...line} />
        <path d="M40 36.7v.9" stroke={INK} strokeWidth="0.85" {...line} />
        <path d="M36.2 38.4q3.8 5.2 7.6 0z" fill={INK} stroke={INK} strokeWidth="0.6" strokeLinejoin="round" />
        <path d="M38 40.6q2 1.4 4 0q-.6 1.2 -2 1.3q-1.4 -.1 -2 -1.3z" fill="#E5675A" />
      </>
    );
  }

  // Worried: open eyes, brows raised in the middle, a small frown.
  return (
    <>
      <ellipse cx="34.6" cy="28.4" rx="2.9" ry="3.3" fill="#fff" />
      <ellipse cx="45.4" cy="28.4" rx="2.9" ry="3.3" fill="#fff" />
      <circle cx="35.1" cy="29.2" r="2" fill="#6B3412" />
      <circle cx="44.9" cy="29.2" r="2" fill="#6B3412" />
      <circle cx="35.1" cy="29.3" r="1" fill={INK} />
      <circle cx="44.9" cy="29.3" r="1" fill={INK} />
      <circle cx="35.8" cy="28.4" r="0.55" fill="#fff" />
      <circle cx="45.6" cy="28.4" r="0.55" fill="#fff" />
      <path d="M31.6 24.8l5.6 -1.8M48.4 24.8l-5.6 -1.8" stroke={BROW} strokeWidth="1" {...line} />
      <path d="M40 36.7v1.2M37 40.6q3 -2.2 6 0" stroke={INK} strokeWidth="0.85" {...line} />
    </>
  );
}

export function LionMark({ size = 36, mood = "happy" }: { size?: number; mood?: Mood }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 120 80"
      width={size * 1.5}
      height={size}
      aria-hidden="true"
      focusable="false"
      style={{ transition: "transform 0.3s ease" }}
    >
      {/* Fixed artwork (constant markup from lionArt.ts), then the mood. */}
      <g dangerouslySetInnerHTML={{ __html: LION_BODY }} />
      <Face mood={mood} />
    </svg>
  );
}
