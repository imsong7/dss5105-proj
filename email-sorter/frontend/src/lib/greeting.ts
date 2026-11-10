export type DayPeriod = "morning" | "afternoon" | "evening" | "night";

export interface PeriodTheme {
  greeting: string;
  /** CSS gradient for the banner. */
  background: string;
  /** Main and secondary text colors that stay readable on that gradient. */
  ink: string;
  muted: string;
  /** Icon tile colors. */
  iconBg: string;
  iconFg: string;
}

export const PERIODS: Record<DayPeriod, PeriodTheme> = {
  morning: {
    greeting: "Good morning",
    background: "linear-gradient(135deg, #fff6e5 0%, #ffe3b3 100%)",
    ink: "#3b2a0a",
    muted: "#7a5a1c",
    iconBg: "#ffd37a",
    iconFg: "#7a4a00",
  },
  afternoon: {
    greeting: "Good afternoon",
    background: "linear-gradient(135deg, #eef6ff 0%, #cfe5ff 100%)",
    ink: "#0d2a4d",
    muted: "#3d5f8a",
    iconBg: "#a9d0ff",
    iconFg: "#0b4a99",
  },
  evening: {
    greeting: "Good evening",
    background: "linear-gradient(135deg, #ffeadf 0%, #ffc9c0 100%)",
    ink: "#4a1d12",
    muted: "#8a4a3a",
    iconBg: "#ffb199",
    iconFg: "#8a2b12",
  },
  night: {
    greeting: "Good night",
    background: "linear-gradient(135deg, #1a2447 0%, #2d3a73 100%)",
    ink: "#f4f6ff",
    muted: "#b6c0ea",
    iconBg: "#3d4c8f",
    iconFg: "#ffe9a8",
  },
};

/** Hour of day in Singapore, matching how deadlines are read. */
export function singaporeHour(now: Date = new Date()): number {
  return Number(
    new Intl.DateTimeFormat("en-GB", {
      hour: "numeric",
      hour12: false,
      timeZone: "Asia/Singapore",
    }).format(now),
  ) % 24;
}

export function periodOf(now: Date = new Date()): DayPeriod {
  const hour = singaporeHour(now);

  if (hour >= 5 && hour < 12) return "morning";
  if (hour >= 12 && hour < 17) return "afternoon";
  if (hour >= 17 && hour < 21) return "evening";
  return "night";
}

/** "john.tan2@u.nus.edu" -> "John". Empty when there is no signed-in account. */
export function firstName(email: string): string {
  const local = email.split("@")[0] ?? "";
  const word = local.split(/[._\-+]+/).find((part) => /[a-z]/i.test(part)) ?? "";
  const letters = word.replace(/\d+$/g, "").replace(/\d/g, "");

  return letters ? letters.charAt(0).toUpperCase() + letters.slice(1).toLowerCase() : "";
}
