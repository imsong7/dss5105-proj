import { AlertCircle, Clock, Info, Reply } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { ActionKey } from "../domain/taxonomy";
import { REPLY_NATURE } from "../domain/taxonomy";

const ACTION_STYLES: Record<
  ActionKey,
  { box: string; icon: LucideIcon }
> = {
  needs_action: {
    box: "text-action-now-fg",
    icon: AlertCircle,
  },
  needs_reply: {
    box: "text-action-reply-fg",
    icon: Reply,
  },
  reminder: {
    box: "text-action-reminder-fg",
    icon: Clock,
  },
  no_immediate_action: {
    box: "text-muted",
    icon: Info,
  },
};

const SIZES = {
  sm: "gap-1 text-[12px]",
  md: "gap-1.5 text-[13px]",
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
      className={`inline-flex items-center font-semibold ${box} ${SIZES[size]}`}
    >
      <Icon className={ICON_SIZES[size]} aria-hidden="true" />
      <span>{REPLY_NATURE[action]}</span>
    </span>
  );
}
