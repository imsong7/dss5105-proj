import { useLayoutEffect, useRef, useState } from "react";
import { CalendarDays, Inbox, ListChecks, Monitor, Moon, Search, Sun } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useTheme } from "../hooks/useTheme";
import type { ThemePref } from "../hooks/useTheme";
import { LionMark } from "./LionMark";
import type { Mood } from "./LionMark";

export type WorkspaceView = "today" | "inbox" | "calendar";

const VIEWS: readonly {
  key: WorkspaceView;
  label: string;
  icon: LucideIcon;
}[] = [
  { key: "today", label: "Today", icon: ListChecks },
  { key: "inbox", label: "Inbox", icon: Inbox },
  { key: "calendar", label: "Calendar", icon: CalendarDays },
];

const THEME_NEXT: Record<ThemePref, ThemePref> = { auto: "light", light: "dark", dark: "auto" };
const THEME_LABEL: Record<ThemePref, string> = {
  auto: "Theme: follows your device",
  light: "Theme: light",
  dark: "Theme: dark",
};

function ThemeToggle() {
  const { pref, setPref } = useTheme();
  const Icon = pref === "dark" ? Moon : pref === "light" ? Sun : Monitor;

  return (
    <button
      type="button"
      onClick={() => setPref(THEME_NEXT[pref])}
      aria-label={`${THEME_LABEL[pref]}. Change`}
      title={THEME_LABEL[pref]}
      className="press grid h-11 w-11 place-items-center rounded-full text-muted hover:bg-surface-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
    >
      <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
    </button>
  );
}

function UserChip({ email, name }: { email: string; name: string }) {
  if (!email) {
    return null;
  }

  return (
    <div className="inline-flex min-h-11 items-center gap-2 rounded-full border border-line bg-surface py-1 pr-1.5 pl-1.5">
      <span
        className="grid h-8 w-8 place-items-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent"
        aria-hidden="true"
      >
        {(name || email).slice(0, 2).toUpperCase()}
      </span>
      <span
        title={email}
        className="hidden max-w-[220px] truncate text-[13px] font-medium text-ink sm:inline"
      >
        {name || email}
      </span>
      <form method="post" action="/logout">
        <button
          type="submit"
          className="min-h-11 rounded-full px-2.5 sm:px-3 text-[13px] font-medium text-muted hover:bg-surface-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}

interface AppHeaderProps {
  userEmail: string;
  userName: string;
  /** Wide screens: let the page colour show through (Today). */
  overlay?: boolean;
  progress: { done: number; total: number } | null;
  mood?: Mood;
  onShowHelp: () => void;
  onOpenPalette: () => void;
  view: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
}

export function AppHeader({ userEmail, userName, overlay = false, progress, mood, onShowHelp, onOpenPalette, view, onViewChange }: AppHeaderProps) {
  const list = useRef<HTMLUListElement>(null);
  const [pill, setPill] = useState<{ left: number; width: number } | null>(null);

  // The white pill slides to the active tab instead of jumping.
  useLayoutEffect(() => {
    function place() {
      const active = list.current?.querySelector<HTMLElement>('[aria-current="page"]');
      if (active) {
        setPill({ left: active.offsetLeft, width: active.offsetWidth });
      }
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [view]);

  return (
    <>
    <header
      className={`sticky top-0 z-20 border-b border-line/80 bg-surface/88 pt-[env(safe-area-inset-top)] backdrop-blur-xl max-sm:hidden ${
        overlay ? "lg:bg-surface/78" : ""
      }`}
    >
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-2.5 sm:px-6 lg:px-8">
        <div className="flex items-center gap-2.5">
          <span className="grid h-10 w-10 place-items-center overflow-hidden rounded-xl bg-accent-soft ring-1 ring-accent/10">
            <LionMark size={42} mood={mood} />
          </span>
          <span>
            <span className="block text-[14px] font-bold tracking-[-0.01em] text-ink">Scholar Inbox</span>
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-muted uppercase">Graduate workspace</span>
          </span>
        </div>

        <nav aria-label="Views" className="max-sm:hidden">
          <ul ref={list} className="relative flex items-center gap-0.5 rounded-xl bg-surface-muted/90 p-1">
            {pill ? (
              <li
                aria-hidden="true"
                className="absolute top-1 bottom-1 rounded-lg bg-surface shadow-[0_1px_4px_rgba(16,24,40,0.10)] ring-1 ring-black/5 transition-[left,width] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]"
                style={{ left: pill.left, width: pill.width }}
              />
            ) : null}
            {VIEWS.map(({ key, label, icon: Icon }) => {
              const active = view === key;

              return (
                <li key={key} className="flex flex-1 sm:block">
                  <button
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => onViewChange(key)}
                    className={`press relative inline-flex min-h-10 w-full items-center justify-center gap-1.5 rounded-lg px-4 py-1.5 text-[13px] transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface-muted focus-visible:outline-none sm:w-auto ${
                      active
                        ? "font-semibold text-accent"
                        : "font-medium text-muted hover:text-ink"
                    }`}
                  >
                    <Icon
                      className={`h-3.5 w-3.5 ${active ? "text-accent" : ""}`}
                      aria-hidden="true"
                    />
                    {label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="order-2 ml-auto sm:order-none">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onOpenPalette}
              aria-label="Search and jump (Ctrl or Command K)"
              title="Jump to anything (⌘K)"
              className="press hidden min-h-10 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-[13px] text-muted shadow-sm hover:border-accent/30 hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none lg:inline-flex"
            >
              <Search className="h-3.5 w-3.5" aria-hidden="true" />
              Jump to…
              <kbd className="rounded border border-line bg-surface-muted px-1.5 font-mono text-[11px]">⌘K</kbd>
            </button>
            <button
              type="button"
              onClick={onShowHelp}
              aria-label="Keyboard shortcuts"
              title="Keyboard shortcuts (?)"
              className="hidden h-11 w-11 place-items-center rounded-full text-[14px] font-semibold text-muted hover:bg-surface-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none lg:grid"
            >
              ?
            </button>
            <ThemeToggle />
            <UserChip email={userEmail} name={userName} />
          </div>
        </div>
      </div>
      {progress ? (
        <div
          role="progressbar"
          aria-label="Sorting mail"
          aria-valuemin={0}
          aria-valuemax={progress.total}
          aria-valuenow={progress.done}
          className="absolute inset-x-0 bottom-0 h-0.5 bg-transparent max-sm:hidden"
        >
          <div
            className="h-full bg-accent transition-[width] duration-300"
            style={{ width: `${(progress.done / Math.max(1, progress.total)) * 100}%` }}
          />
        </div>
      ) : null}
    </header>
      {/* On phones the top bar is gone; sorting progress is a thin line at the very top. */}
      {progress ? (
        <div
          role="progressbar"
          aria-label="Sorting mail"
          aria-valuemin={0}
          aria-valuemax={progress.total}
          aria-valuenow={progress.done}
          className="fixed inset-x-0 top-0 z-40 h-0.5 sm:hidden"
        >
          <div
            className="h-full bg-accent transition-[width] duration-300"
            style={{ width: `${(progress.done / Math.max(1, progress.total)) * 100}%` }}
          />
        </div>
      ) : null}
    </>
  );
}

/** Phone-only tab bar fixed to the bottom, within reach of the thumb. */
export function BottomNav({
  view,
  onViewChange,
}: {
  view: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
}) {
  return (
    <nav
      aria-label="Views"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden"
    >
      <ul className="mx-auto grid max-w-md grid-cols-3">
        {VIEWS.map(({ key, label, icon: Icon }) => {
          const active = view === key;

          return (
            <li key={key}>
              <button
                type="button"
                aria-current={active ? "page" : undefined}
                onClick={() => onViewChange(key)}
                className={`press flex min-h-14 w-full flex-col items-center justify-center gap-0.5 text-[11px] focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset focus-visible:outline-none ${
                  active ? "font-semibold text-accent" : "font-medium text-muted"
                }`}
              >
                <span
                  className={`grid h-7 w-14 place-items-center rounded-full transition-colors duration-300 ${
                    active ? "bg-accent-soft" : ""
                  }`}
                >
                  <Icon className="h-[19px] w-[19px]" aria-hidden="true" />
                </span>
                {label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
