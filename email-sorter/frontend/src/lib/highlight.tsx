import type { ReactNode } from "react";

/** The text with every match of `query` wrapped in <mark>. */
export function highlight(text: string, query: string): ReactNode {
  const needle = query.trim();
  if (!needle) {
    return text;
  }

  const lower = text.toLowerCase();
  const target = needle.toLowerCase();
  const parts: ReactNode[] = [];
  let from = 0;

  for (let at = lower.indexOf(target); at !== -1; at = lower.indexOf(target, from)) {
    if (at > from) {
      parts.push(text.slice(from, at));
    }
    parts.push(
      <mark key={at} className="rounded-[3px] bg-highlight/30 px-0.5 text-inherit">
        {text.slice(at, at + target.length)}
      </mark>,
    );
    from = at + target.length;
  }

  if (from === 0) {
    return text;
  }
  parts.push(text.slice(from));
  return parts;
}

/** A short piece of the body around the first match, or "" when there is none. */
export function bodySnippet(body: string, query: string, radius = 36): string {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return "";
  }

  const flat = body.replace(/\s+/g, " ");
  const at = flat.toLowerCase().indexOf(needle);
  if (at === -1) {
    return "";
  }

  const start = Math.max(0, at - radius);
  const end = Math.min(flat.length, at + needle.length + radius);
  return `${start > 0 ? "…" : ""}${flat.slice(start, end)}${end < flat.length ? "…" : ""}`;
}
