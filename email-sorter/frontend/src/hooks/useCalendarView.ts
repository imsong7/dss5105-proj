import { useMemo, useState } from "react";

import { academicMarkersOn, upcomingAcademic } from "../domain/academic";
import {
  academicEventsOn,
  buildDeadlines,
  buildMonthCells,
  courseLegend,
  monthKeyOf,
  shiftMonth,
  todayKey,
} from "../domain/calendar";
import type {
  AcademicEvent,
  CalendarDeadline,
  PersonalEvent,
} from "../domain/calendar";
import type { InboxEmail } from "../domain/email";

const NO_DEADLINES: readonly CalendarDeadline[] = [];
const NO_ACADEMIC: readonly AcademicEvent[] = [];

export function useCalendarView(
  emails: readonly InboxEmail[],
  academicEvents: readonly AcademicEvent[] = [],
  personalEvents: readonly PersonalEvent[] = [],
  /** Dates the student put in the calendar from the Inbox (Canvas due dates need not). */
  isInCalendar?: (key: string) => boolean,
) {
  const today = todayKey();
  const [showAcademic, setShowAcademic] = useState(true);
  const deadlines = useMemo(
    () => buildDeadlines(emails, personalEvents, isInCalendar),
    [emails, personalEvents, isInCalendar],
  );

  const courses = useMemo(() => courseLegend(deadlines), [deadlines]);

  const deadlinesByDate = useMemo(() => {
    const map = new Map<string, CalendarDeadline[]>();

    for (const deadline of deadlines) {
      const list = map.get(deadline.date);

      if (list) {
        list.push(deadline);
      } else {
        map.set(deadline.date, [deadline]);
      }
    }

    return map;
  }, [deadlines]);

  const [month, setMonth] = useState(() => monthKeyOf(today));
  const [selectedDate, setSelectedDate] = useState(today);

  const cells = useMemo(() => buildMonthCells(month), [month]);

  const monthDeadlines = useMemo(
    () => deadlines.filter((deadline) => monthKeyOf(deadline.date) === month),
    [deadlines, month],
  );

  const selectedDeadlines = deadlinesByDate.get(selectedDate) ?? NO_DEADLINES;

  const upcoming = useMemo(
    () => deadlines.filter((deadline) => deadline.date > selectedDate).slice(0, 4),
    [deadlines, selectedDate],
  );

  const selectedAcademic = useMemo(
    () => academicEventsOn(showAcademic ? academicEvents : NO_ACADEMIC, selectedDate),
    [academicEvents, selectedDate, showAcademic],
  );

  const visibleAcademic = showAcademic ? academicEvents : NO_ACADEMIC;

  const academicMarkers = (date: string) =>
    academicMarkersOn(visibleAcademic, date);

  const upcomingAcademicEvents = useMemo(
    () => upcomingAcademic(visibleAcademic, selectedDate, 3),
    [visibleAcademic, selectedDate],
  );

  const academicTones = useMemo(
    () => [...new Set(academicEvents.map((event) => event.category))],
    [academicEvents],
  );

  function selectDate(date: string) {
    setSelectedDate(date);
    setMonth(monthKeyOf(date));
  }

  function goToMonth(delta: number) {
    const nextMonth = shiftMonth(month, delta);
    setMonth(nextMonth);
    setSelectedDate(`${nextMonth}-01`);
  }

  function goToToday() {
    setMonth(monthKeyOf(today));
    setSelectedDate(today);
  }

  return {
    deadlines,
    courses,
    deadlinesByDate,
    month,
    cells,
    selectedDate,
    selectedDeadlines,
    selectedAcademic,
    academicMarkers,
    academicVisible: visibleAcademic,
    academicAll: academicEvents,
    upcomingAcademicEvents,
    academicCategories: academicTones,
    hasAcademic: academicEvents.length > 0,
    showAcademic,
    setShowAcademic,
    upcoming,
    monthDeadlines,
    monthCount: monthDeadlines.length,
    todayKey: today,
    selectDate,
    goToMonth,
    goToToday,
  };
}

export type CalendarView = ReturnType<typeof useCalendarView>;
