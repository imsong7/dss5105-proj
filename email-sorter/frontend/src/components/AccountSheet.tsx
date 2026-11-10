import { KeyRound, Monitor, Moon, Pencil, Plug, Sun, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useTheme } from "../hooks/useTheme";
import type { ThemePref } from "../hooks/useTheme";
import { BottomSheet } from "./BottomSheet";

const THEMES: readonly { key: ThemePref; label: string; icon: LucideIcon }[] = [
  { key: "auto", label: "Device", icon: Monitor },
  { key: "light", label: "Light", icon: Sun },
  { key: "dark", label: "Dark", icon: Moon },
];

/** Phone-only: the things the top bar holds on larger screens. */
export function AccountSheet({
  open,
  onClose,
  name,
  email,
  onEditName,
  onOpenSetup,
  onSwitchSource,
  pushedMail,
}: {
  open: boolean;
  onClose: () => void;
  name: string;
  email: string;
  onEditName: () => void;
  onOpenSetup?: () => void;
  /** Present when the student may choose how mail reaches the app. */
  onSwitchSource?: () => void;
  pushedMail: boolean;
}) {
  const { pref, setPref } = useTheme();
  const sources = [
    { pushed: true, label: "Power Automate", icon: Workflow },
    { pushed: false, label: "Outlook token", icon: KeyRound },
  ];

  return (
    <BottomSheet open={open} label="Account and settings" onClose={onClose}>
      <div className="flex items-center gap-3 pb-3">
        <span
          aria-hidden="true"
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-accent-soft text-[13px] font-semibold text-accent"
        >
          {(name || email).slice(0, 2).toUpperCase()}
        </span>
        <div className="min-w-0">
          <p className="truncate text-[15px] font-semibold text-ink">{name || email}</p>
          {name ? <p className="truncate text-[13px] text-muted">{email}</p> : null}
        </div>
      </div>

      <p className="mb-1.5 text-[12px] font-medium text-muted">Theme</p>
      <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-1 rounded-[10px] bg-surface-muted p-0.5">
        {THEMES.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={pref === key}
            onClick={() => setPref(key)}
            className={`press inline-flex min-h-11 items-center justify-center gap-1.5 rounded-[8px] text-[13px] focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
              pref === key
                ? "bg-surface font-semibold text-accent shadow-[0_1px_3px_rgba(0,0,0,0.10)]"
                : "font-medium text-muted"
            }`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>

      {onSwitchSource ? (
        <>
          <p className="mt-4 mb-1.5 text-[12px] font-medium text-muted">Get mail with</p>
          <div
            role="radiogroup"
            aria-label="Get mail with"
            className="grid grid-cols-2 gap-1 rounded-[10px] bg-surface-muted p-0.5"
          >
            {sources.map(({ pushed, label, icon: Icon }) => {
              const active = pushed === pushedMail;
              return (
                <button
                  key={label}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => {
                    if (!active) {
                      onSwitchSource();
                    }
                  }}
                  className={`press inline-flex min-h-11 items-center justify-center gap-1.5 rounded-[8px] text-[13px] focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
                    active
                      ? "bg-surface font-semibold text-accent shadow-[0_1px_3px_rgba(0,0,0,0.10)]"
                      : "font-medium text-muted"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                  {label}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[12px] leading-4 text-muted">
            {pushedMail
              ? "Your flow sends mail on its own. A token is quicker to set up but lasts about an hour."
              : "Paste a token each visit. Power Automate takes a few minutes once, then works on its own."}
          </p>
        </>
      ) : null}

      <button
        type="button"
        onClick={() => {
          onClose();
          onEditName();
        }}
        className="mt-3 flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2 text-left text-[14px] text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
      >
        <Pencil className="h-4 w-4 text-muted" aria-hidden="true" />
        Change your name
      </button>

      {onOpenSetup ? (
        <button
          type="button"
          onClick={() => {
            onClose();
            onOpenSetup();
          }}
          className="flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2 text-left text-[14px] text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <Plug className="h-4 w-4 text-muted" aria-hidden="true" />
          Connect Outlook
        </button>
      ) : null}

      <form method="post" action="/logout">
        <button
          type="submit"
          className="flex min-h-11 w-full items-center rounded-lg px-2 text-left text-[14px] font-medium text-action-now-fg hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          Sign out
        </button>
      </form>
    </BottomSheet>
  );
}
