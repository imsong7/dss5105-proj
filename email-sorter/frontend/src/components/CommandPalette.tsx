import { CalendarDays, CornerDownLeft, Inbox, ListChecks, Mail, Plug, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { InboxEmail } from "../domain/email";
import type { WorkspaceView } from "./AppHeader";

interface Command {
  id: string;
  label: string;
  hint: string;
  icon: typeof Mail;
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  emails: readonly InboxEmail[];
  courses: readonly { code: string; hue: number }[];
  onGo: (view: WorkspaceView) => void;
  onOpenEmail: (id: string) => void;
  onOpenCourse: (code: string) => void;
  onOpenSetup?: () => void;
  onSwitchSource?: () => void;
  pushedMail?: boolean;
}

const MAX_RESULTS = 8;

/** Ctrl/Cmd+K: jump to a tab, a course or an email by typing a few letters. */
export function CommandPalette({
  open,
  onClose,
  emails,
  courses,
  onGo,
  onOpenEmail,
  onOpenCourse,
  onOpenSetup,
  onSwitchSource,
  pushedMail = false,
}: CommandPaletteProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) {
      return;
    }
    if (open && !dialog.open) {
      setQuery("");
      setActive(0);
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const results = useMemo<Command[]>(() => {
    const needle = query.trim().toLowerCase();
    const pages: Command[] = [
      { id: "go-today", label: "Today", hint: "Go to", icon: ListChecks, run: () => onGo("today") },
      { id: "go-inbox", label: "Inbox", hint: "Go to", icon: Inbox, run: () => onGo("inbox") },
      { id: "go-calendar", label: "Calendar", hint: "Go to", icon: CalendarDays, run: () => onGo("calendar") },
    ];
    if (onOpenSetup) {
      pages.push({ id: "setup", label: "Connect Outlook", hint: "Setup guide", icon: Plug, run: onOpenSetup });
    }
    if (onSwitchSource) {
      pages.push({
        id: "source",
        label: pushedMail ? "Use an Outlook token instead" : "Use Power Automate instead",
        hint: "Mail source",
        icon: Plug,
        run: onSwitchSource,
      });
    }
    const courseItems: Command[] = courses.map((course) => ({
      id: `course-${course.code}`,
      label: course.code,
      hint: "Course",
      icon: CalendarDays,
      run: () => onOpenCourse(course.code),
    }));
    const mailItems: Command[] = emails.map((email) => ({
      id: `mail-${email.id}`,
      label: email.subject,
      hint: email.sender.name,
      icon: Mail,
      run: () => onOpenEmail(email.id),
    }));

    if (!needle) {
      return [...pages, ...courseItems].slice(0, MAX_RESULTS);
    }

    return [...pages, ...courseItems, ...mailItems]
      .filter((item) => `${item.label} ${item.hint}`.toLowerCase().includes(needle))
      .slice(0, MAX_RESULTS);
  }, [query, emails, courses, onGo, onOpenEmail, onOpenCourse, onOpenSetup, onSwitchSource, pushedMail]);

  function choose(command: Command | undefined) {
    if (command) {
      onClose();
      command.run();
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) {
          onClose();
        }
      }}
      aria-label="Jump to"
      className="palette m-auto mt-[12vh] w-[min(560px,calc(100%-24px))] overflow-hidden rounded-2xl border border-line bg-surface p-0 text-ink shadow-[0_24px_60px_rgba(0,0,0,0.3)]"
    >
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
        <input
          autoFocus
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((index) => Math.min(results.length - 1, index + 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((index) => Math.max(0, index - 1));
            } else if (event.key === "Enter") {
              event.preventDefault();
              choose(results[active]);
            }
          }}
          placeholder="Search mail, courses, tabs"
          aria-label="Search mail, courses, tabs"
          className="min-h-14 w-full bg-transparent text-[15px] outline-none placeholder:text-muted"
        />
      </div>
      <ul role="listbox" aria-label="Results" className="max-h-[50vh] overflow-y-auto p-2">
        {results.length === 0 ? (
          <li className="px-3 py-6 text-center text-[14px] text-muted">No match</li>
        ) : (
          results.map((item, index) => {
            const Icon = item.icon;
            return (
              <li key={item.id} role="option" aria-selected={index === active}>
                <button
                  type="button"
                  onMouseMove={() => setActive(index)}
                  onClick={() => choose(item)}
                  className={`flex min-h-11 w-full items-center gap-3 rounded-[10px] px-3 text-left transition-colors ${
                    index === active ? "bg-accent-soft" : ""
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate text-[14px] font-medium">{item.label}</span>
                  <span className="max-w-[40%] shrink-0 truncate text-[12px] text-muted">{item.hint}</span>
                  {index === active ? (
                    <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
                  ) : null}
                </button>
              </li>
            );
          })
        )}
      </ul>
    </dialog>
  );
}
