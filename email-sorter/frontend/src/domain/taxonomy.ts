/**
 * Frontend mirror of email-sorter/app/taxonomy.py.
 *
 * Keys and labels are duplicated here on purpose: the prototype must not
 * depend on the Flask app. A future adapter can refresh these labels from
 * GET /api/taxonomy instead of hard-coding them.
 */

export const CONTENT_CATEGORIES = {
  medical: "Medical",
  promotional: "Promotional",
  career: "Career related",
  canva: "Canva",
  general: "General",
  others: "Others",
} as const;

export type CategoryKey = keyof typeof CONTENT_CATEGORIES;

export const REPLY_NATURE = {
  needs_action: "Needs action",
  needs_reply: "Needs a reply",
  reminder: "Reminder",
  no_immediate_action: "Further review",
} as const;

export type ActionKey = keyof typeof REPLY_NATURE;

export const CATEGORY_KEYS = Object.keys(CONTENT_CATEGORIES) as CategoryKey[];
export const ACTION_KEYS = Object.keys(REPLY_NATURE) as ActionKey[];
