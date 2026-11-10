import { AlertCircle, Clock, Info, Reply } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { ActionKey } from "../domain/taxonomy";
import { REPLY_NATURE } from "../domain/taxonomy";

const ACTION_STYLES: Record<
  ActionKey,
  { box: string; icon: LucideIcon }
> = {
  needs_action: {
    box: "border-action-now-line bg-action-now-bg text-action-now-fg",
    icon: AlertCircle,
  },
  needs_reply: {
    box: "border-action-reply-line bg-action-reply-bg text-action-reply-fg",
    icon: Reply,
  },
  reminder: {
    box: "border-action-reminder-line bg-action-reminder-bg text-action-reminder-fg",
    icon: Clock,
  },
  no_immediate_action: {
    box: "border-action-none-line bg-action-none-bg text-action-none-fg",
    icon: Info,
  },
};

const SIZES = {
  sm: "gap-1 px-2 py-[3px] text-[11px]",
  md: "gap-1.5 px-2.5 py-1 text-[13px]",
} as const;

const ICON_SIZES = {
  sm: "h-3 w-3",
  md: "h-3.5 w-3.5",
} as const;

interface StatusBadgeProps {
  action: ActionKey;
  size?: keyof typeof SIZES;
}

export function StatusBadge({ action, size = "sm" }: StatusBadgeProps) {
  const { box, icon: Icon } = ACTION_STYLES[action];

  return (
    <span
      className={`inline-flex items-center rounded-full border font-semibold ${box} ${SIZES[size]}`}
    >
      <Icon className={ICON_SIZES[size]} aria-hidden="true" />
      <span>{REPLY_NATURE[action]}</span>
    </span>
  );
}
