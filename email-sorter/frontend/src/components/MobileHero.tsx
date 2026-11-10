import type { ReactNode } from "react";

import { useAccount } from "../contexts/AccountContext";
import { useTheme } from "../hooks/useTheme";
import { PERIODS, periodOf } from "../lib/greeting";

/**
 * Phone-only page header, the same family as the Today greeting: a tinted
 * panel under the status bar with a large title and the account button.
 */
export function MobileHero({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children?: ReactNode;
}) {
  const account = useAccount();
  const { dark } = useTheme();
  const theme = dark ? PERIODS.night : PERIODS[periodOf()];

  return (
    <header
      style={{ background: theme.background, color: theme.ink }}
      className="relative isolate -mx-4 -mt-5 overflow-hidden rounded-b-[28px] px-6 pt-[calc(1rem+env(safe-area-inset-top))] pb-5 sm:hidden"
    >
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[27px] leading-tight font-semibold tracking-[-0.015em]">{title}</h1>
        {account ? (
          <button
            type="button"
            onClick={account.open}
            aria-label="Account and settings"
            style={{ background: theme.iconBg, color: theme.iconFg }}
            className="press grid h-11 w-11 shrink-0 place-items-center rounded-full text-[13px] font-semibold focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          >
            {account.initials}
          </button>
        ) : null}
      </div>
      {subtitle ? (
        <p style={{ color: theme.muted }} className="mt-0.5 text-[14px]">
          {subtitle}
        </p>
      ) : null}
      {children}
    </header>
  );
}
