import { useEffect, useMemo, useState } from "react";

import { AppHeader, BottomNav } from "./components/AppHeader";
import type { WorkspaceView } from "./components/AppHeader";
import { CalendarPage } from "./components/CalendarPage";
import { CommandPalette } from "./components/CommandPalette";
import { CoursePage } from "./components/CoursePage";
import { InboxPage } from "./components/InboxPage";
import { AccountSheet } from "./components/AccountSheet";
import { NameDialog } from "./components/NameDialog";
import { PullToRefresh } from "./components/PullToRefresh";
import { SetupGuide } from "./components/SetupGuide";
import { ShortcutsDialog } from "./components/ShortcutsDialog";
import { TodayBackdrop } from "./components/TodayBackdrop";
import { TodayPage } from "./components/TodayPage";
import { useToasts } from "./components/Toasts";
import { TokenDialog } from "./components/TokenDialog";
import { addDays, formatDayShort } from "./domain/calendar";
import { buildToday, isEmptyToday } from "./domain/today";
import { periodOf } from "./lib/greeting";
import type { Mood } from "./components/LionMark";
import type { AcademicEvent } from "./domain/calendar";
import { AccountProvider } from "./contexts/AccountContext";
import { CourseProvider } from "./contexts/CourseContext";
import { SavedJobsProvider } from "./contexts/SavedJobsContext";
import { useCalendarView } from "./hooks/useCalendarView";
import { useInboxView } from "./hooks/useInboxView";
import { useFeedSync } from "./hooks/useFeedSync";
import { useItemStates } from "./hooks/useItemStates";
import { usePersonalEvents } from "./hooks/usePersonalEvents";
import { useShortcuts } from "./hooks/useShortcuts";
import { useTheme } from "./hooks/useTheme";
import { fetchAcademicCalendar, fetchSession, saveMailSource, saveName } from "./services/flask";
import type { SessionInfo } from "./services/flask";

const VIEW_KEY = "inbox-sorter.view";

const RETURN_LABEL: Record<WorkspaceView, string> = {
  today: "Back to Today",
  inbox: "Back to inbox",
  calendar: "Back to Calendar",
};

function readView(): WorkspaceView {
  try {
    const stored = window.localStorage.getItem(VIEW_KEY);
    return stored === "inbox" || stored === "calendar" ? stored : "today";
  } catch {
    return "today";
  }
}

function Workspace({ session }: { session: SessionInfo }) {
  const [view, setView] = useState<WorkspaceView>(readView);
  const [academic, setAcademic] = useState<readonly AcademicEvent[]>([]);
  const inbox = useInboxView(session);
  const basePersonal = usePersonalEvents();
  const baseStates = useItemStates();
  const toasts = useToasts();
  const [helpOpen, setHelpOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [course, setCourse] = useState<string | null>(null);
  // Where an email was opened from, so Back returns there and not to the Inbox list.
  const [origin, setOrigin] = useState<{ view: WorkspaceView; course: string | null } | null>(null);
  const [name, setName] = useState(session.name);
  const [nameOpen, setNameOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const { dark: themeDark } = useTheme();
  const pushedMail = session.provider === "powerautomate";
  // Students may swap their Power Automate flow for a quick Outlook token and back.
  // Reloading starts every hook cleanly in the new mode.
  const switchSource = session.canChooseSource
    ? () => {
        void saveMailSource(pushedMail ? "outlook" : "powerautomate")
          .then(() => window.location.reload())
          .catch(() => toasts.push({ text: "Could not switch. Please try again." }));
      }
    : undefined;

  // Wrap saves so every change confirms itself, and done/snooze can be undone.
  const states = useMemo(
    () => ({
      ...baseStates,
      setDone: async (key: string, done: boolean) => {
        await baseStates.setDone(key, done);
        if (done) {
          toasts.push({
            text: "Marked done",
            actionLabel: "Undo",
            onAction: () => void baseStates.setDone(key, false),
          });
        }
      },
      snooze: async (key: string, until: string) => {
        await baseStates.snooze(key, until);
        if (until) {
          toasts.push({
            text: `Hidden until ${formatDayShort(until)}`,
            actionLabel: "Undo",
            onAction: () => void baseStates.snooze(key, ""),
          });
        }
      },
    }),
    [baseStates, toasts],
  );

  const personal = useMemo(
    () => ({
      ...basePersonal,
      save: async (draft: Parameters<typeof basePersonal.save>[0], id?: string) => {
        await basePersonal.save(draft, id);
        toasts.push({ text: id ? "Event updated" : "Event added" });
      },
      remove: async (id: string) => {
        await basePersonal.remove(id);
        toasts.push({ text: "Event deleted" });
      },
    }),
    [basePersonal, toasts],
  );
  const calendar = useCalendarView(inbox.emails, academic, personal.events, baseStates.isInCalendar);
  // The logo's face reflects the day: something just missed worries it, a clear
  // list ahead cheers it. Older overdue items are left out on purpose.
  const recentCutoff = addDays(calendar.todayKey, -3);
  const todaySections = buildToday(calendar.deadlines, inbox.emails, calendar.todayKey, (key) =>
    states.isHidden(key, calendar.todayKey),
  );
  const mood: Mood = !inbox.hasLoaded
    ? "happy"
    : todaySections.overdue.some((item) => item.date >= recentCutoff)
      ? "worried"
      : inbox.total > 0 && isEmptyToday({ ...todaySections, overdue: [] })
        ? "cheer"
        : periodOf() === "night"
          ? "sleepy"
          : "happy";
  useFeedSync(calendar.deadlines, states.isDone, inbox.hasLoaded);

  const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
  const recentOverdue = todaySections.overdue.filter((item) => item.date >= recentCutoff).length;
  const lionStatus = !inbox.hasLoaded
    ? "Load your mail and I'll sort it for you."
    : recentOverdue > 0
      ? `${plural(recentOverdue, "thing")} slipped past. Let's catch up.`
      : todaySections.today.length > 0
        ? `${plural(todaySections.today.length, "thing")} due today.`
        : todaySections.reply.length > 0
          ? `${plural(todaySections.reply.length, "email")} waiting for your reply.`
          : todaySections.soon.length > 0
            ? `Nothing today. ${plural(todaySections.soon.length, "deadline")} this week.`
            : inbox.syncing || !inbox.mailComplete
              ? "Nothing due in the mail so far."
              : "All clear. Nice work.";

  useEffect(() => {
    const abort = new AbortController();
    void fetchAcademicCalendar(abort.signal).then((data) =>
      setAcademic(data.events),
    );
    return () => abort.abort();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useShortcuts({
    goTo: (next) => changeView(next),
    focusSearch: () => {
      changeView("inbox");
      window.requestAnimationFrame(() =>
        document.getElementById("inbox-search")?.focus(),
      );
    },
    move: (delta) => {
      if (view === "inbox") {
        inbox.moveSelection(delta);
      }
    },
    toggleHandled: () => {
      if (view === "inbox" && inbox.selectedId) {
        void states.setDone(inbox.selectedId, !states.isDone(inbox.selectedId));
      }
    },
    showHelp: () => setHelpOpen(true),
  });

  function changeView(next: WorkspaceView) {
    setCourse(null);
    setOrigin(null);
    if (next === "calendar") {
      inbox.closeMobileDetail();
    }

    setView(next);
    try {
      window.localStorage.setItem(VIEW_KEY, next);
    } catch {
      // The tab simply will not be remembered.
    }
  }

  function openDateInCalendar(date: string) {
    setCourse(null);
    calendar.selectDate(date);
    setView("calendar");
  }

  function openEmailFromCalendar(id: string) {
    // Remember the screen the email was opened from (not the Inbox itself).
    setOrigin(view === "inbox" ? null : { view, course });
    setCourse(null);
    inbox.openEmail(id);
    setView("inbox");
  }

  function returnToOrigin() {
    if (!origin) {
      return;
    }
    inbox.closeMobileDetail();
    setView(origin.view);
    setCourse(origin.course);
    setOrigin(null);
  }

  return (
    <SavedJobsProvider>
    <CourseProvider value={setCourse}>
    <AccountProvider value={{ initials: (name || session.email).slice(0, 2).toUpperCase(), open: () => setAccountOpen(true), openSetup: pushedMail ? () => setSetupOpen(true) : undefined, switchSource }}>
    <div className="app-shell relative isolate flex min-h-dvh max-w-full flex-col overflow-x-clip pb-[calc(3.5rem+env(safe-area-inset-bottom))] max-sm:pt-[env(safe-area-inset-top)] sm:pb-0 lg:h-dvh lg:overflow-hidden">
      {view === "today" && !course ? <TodayBackdrop /> : null}
      <AppHeader
        // The night band is dark, so dark header text would vanish on it in light mode.
        overlay={view === "today" && !course && (themeDark || periodOf() !== "night")}
        userEmail={session.email}
        userName={name}
        progress={inbox.loading || inbox.receiving ? null : inbox.progress}
        mood={mood}
        status={lionStatus}
        onShowHelp={() => setHelpOpen(true)}
        onOpenPalette={() => setPaletteOpen(true)}
        view={view}
        onViewChange={changeView}
      />

      <div key={view} className="view-enter flex flex-1 flex-col lg:min-h-0">
      {course ? (
        <CoursePage
          code={course}
          calendar={calendar}
          emails={inbox.emails}
          onBack={() => setCourse(null)}
          onOpenEmail={openEmailFromCalendar}
        />
      ) : view === "today" ? (
        <TodayPage
          inbox={inbox}
          calendar={calendar}
          states={states}
          name={name}
          onEditName={() => setNameOpen(true)}
          mood={mood}
          initials={(name || session.email).slice(0, 2).toUpperCase()}
          onOpenAccount={() => setAccountOpen(true)}
          onOpenEmail={openEmailFromCalendar}
          onOpenDate={openDateInCalendar}
        />
      ) : view === "inbox" ? (
        <InboxPage
          view={inbox}
          states={states}
          returnLabel={origin ? RETURN_LABEL[origin.view] : undefined}
          onReturn={origin ? returnToOrigin : undefined}
        />
      ) : (
        <CalendarPage
          view={calendar}
          onOpenEmail={openEmailFromCalendar}
          onSaveEvent={personal.save}
          onDeleteEvent={personal.remove}
          loading={inbox.loading || inbox.receiving || inbox.syncing}
        />
      )}
      </div>
      <TokenDialog
        open={inbox.tokenDialogOpen}
        initial={inbox.token}
        onSubmit={inbox.submitToken}
        onClose={inbox.closeTokenDialog}
        onSwitchSource={switchSource}
      />
      <NameDialog
        open={nameOpen}
        current={name}
        onSave={async (next) => {
          setName(await saveName(next));
        }}
        onClose={() => setNameOpen(false)}
      />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        emails={inbox.emails}
        courses={calendar.courses}
        onGo={changeView}
        onOpenSetup={pushedMail ? () => setSetupOpen(true) : undefined}
        onSwitchSource={switchSource}
        pushedMail={pushedMail}
        onOpenEmail={openEmailFromCalendar}
        onOpenCourse={(code) => {
          setView("today");
          setCourse(code);
        }}
      />
      <AccountSheet
        open={accountOpen}
        onClose={() => setAccountOpen(false)}
        name={name}
        email={session.email}
        onEditName={() => setNameOpen(true)}
        onOpenSetup={pushedMail ? () => setSetupOpen(true) : undefined}
        onSwitchSource={switchSource}
        pushedMail={pushedMail}
      />
      {pushedMail ? (
        <SetupGuide
          open={setupOpen}
          onClose={() => setSetupOpen(false)}
          onSwitchSource={switchSource}
          received={inbox.total}
          onCheck={() => void inbox.load({ announce: true })}
        />
      ) : null}
      <ShortcutsDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
      <PullToRefresh
        enabled={(view === "today" || view === "inbox") && !course && !inbox.mobileDetailOpen}
        busy={inbox.loading}
        onRefresh={() => void inbox.load()}
      />
      <BottomNav view={view} onViewChange={changeView} />

      {toasts.node}
    </div>
    </AccountProvider>
    </CourseProvider>
    </SavedJobsProvider>
  );
}

export default function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    fetchSession(abort.signal)
      .then(setSession)
      .catch((cause: unknown) => {
        if (!abort.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Could not start.");
        }
      });
    return () => abort.abort();
  }, []);

  if (error) {
    return (
      <p role="alert" className="p-8 text-[14px] text-action-now-fg">
        {error}
      </p>
    );
  }

  if (!session) {
    return (
      <p role="status" className="p-8 text-[14px] text-muted">
        Loading…
      </p>
    );
  }

  return <Workspace session={session} />;
}
