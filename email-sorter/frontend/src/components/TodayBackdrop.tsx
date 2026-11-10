import { useTheme } from "../hooks/useTheme";
import { PERIODS, periodOf } from "../lib/greeting";

/**
 * Wide screens only: the Today greeting colour spreads across the top of the
 * page, behind the top bar, and fades out into the page colour.
 */
export function TodayBackdrop() {
  const { dark } = useTheme();
  const theme = dark ? PERIODS.night : PERIODS[periodOf()];
  const fade = "linear-gradient(to bottom, #000 80%, transparent)";

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-x-0 top-0 -z-10 hidden h-[300px] transition-colors duration-500 lg:block"
      style={{ background: theme.background, maskImage: fade, WebkitMaskImage: fade }}
    />
  );
}
