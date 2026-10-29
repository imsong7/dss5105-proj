(() => {
  "use strict";

  const state = {
    emails: [],
    results: new Map(),
    taxonomy: null,
    selectedId: null,
    controller: null,
    calendarMonth: null,
    selectedCalendarDate: null,
    calendarSignature: null,
    academicEvents: [],
    academicLabel: "",
    academicLoaded: false,
    hasFetchedEmails: false,
    userReady: false,
    loading: false,
    loadError: null,
  };

  const priority = {
    needs_action: 0,
    needs_reply: 1,
    reminder: 2,
    no_immediate_action: 3,
  };

  // Dates in this dashboard are always English and shown in Singapore time,
  // regardless of the browser locale.
  const DATE_LOCALE = "en-SG";
  const TIME_ZONE = "Asia/Singapore";

  function setBusy(busy, label = "") {
    const go = $("#go");
    if (!go.dataset.label) go.dataset.label = go.textContent;
    go.disabled = busy;
    go.textContent = busy ? (label || go.dataset.busy || "Working…") : go.dataset.label;
    $("#calendar-fetch").disabled = busy;
    $("#calendar-fetch").textContent = busy ? "Scanning…" : "Scan mailbox";
    $("#backend").disabled = busy;
    $("#cancel").hidden = !busy;
    $("#email-table-wrap")?.setAttribute("aria-busy", String(busy));
  }

  function setGoLabel(text) {
    const go = $("#go");
    go.dataset.label = text;
    if (!go.disabled) go.textContent = text;
  }

  function setProgress(done, total) {
    $("#progress-label").textContent = total ? `Classifying ${done} of ${total}` : "";
  }

  function setProgressDone(total, failed = 0) {
    if (!total) {
      setProgress(0, 0);
      return;
    }
    const classified = total - failed;
    if (failed) {
      $("#progress-label").textContent =
        `Classified ${classified} of ${total} emails (${failed} failed)`;
    } else {
      $("#progress-label").textContent =
        `Classified ${total} email${total === 1 ? "" : "s"}`;
    }
  }

  // Calendar status is a quiet inline note beside the scan button, not a banner.
  function setCalendarStatus(text, isError = false) {
    const status = $("#calendar-status");
    status.textContent = text || "";
    status.classList.toggle("err", Boolean(text) && isError);
  }

  function fillOptions(select, items, allLabel) {
    select.replaceChildren(el("option", { value: "" }, allLabel));
    for (const [key, item] of Object.entries(items)) {
      select.append(el("option", { value: key }, item.label));
    }
  }

  function updateSummary() {
    refreshCourseColors();
    const emails = windowEmails();
    const ids = new Set(emails.map(email => email.id));
    const results = [...state.results.entries()]
      .filter(([id]) => ids.has(id))
      .map(([, result]) => result);
    $("#count-total").textContent = emails.length;
    $("#count-action").textContent = results.filter(r => r.reply_nature === "needs_action").length;
    $("#count-reply").textContent = results.filter(r => r.reply_nature === "needs_reply").length;
    const deadlines = calendarEmails(emails);
    $("#calendar-count").textContent = deadlines.length;
    // Rebuild the calendar when the window or the deadline set changes, but not
    // on every classification tick (deadlines are fixed at load time).
    const bounds = readWindow();
    const signature = `${bounds.since || ""}|${bounds.before || ""}|` + deadlines
      .map(email => `${email.id}:${email.deadline_candidate.date}:${email.deadline_candidate.due_at || ""}`)
      .join("|");
    if (signature !== state.calendarSignature) {
      state.calendarSignature = signature;
      renderCalendar();
    }
  }

  function updateQuickButtons(filter) {
    for (const [id, active] of [
      ["quick-all", filter === "all"],
      ["quick-action", filter === "action"],
      ["quick-reply", filter === "reply"],
    ]) {
      const button = $(`#${id}`);
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    }
  }

  function setQuickFilter(filter) {
    if (filter === "all") {
      $("#search").value = "";
      $("#filter-content").value = "";
    }
    $("#filter-reply").value = filter === "action" || filter === "reply" ? `needs_${filter}` : "";
    updateQuickButtons(filter);
    renderRows();
  }

  function timestamp(email) {
    const value = Date.parse(email.received);
    return Number.isFinite(value) ? value : 0;
  }

  // The time window filters the emails already loaded in this browser; it does
  // not fetch again. Both the list and the calendar use the same selection.
  function windowEmails() {
    const { since, before } = readWindow();
    const sinceMs = since ? Date.parse(since) : null;
    const beforeMs = before ? Date.parse(before) : null;
    return state.emails.filter(email => {
      const value = Date.parse(email.received);
      if (!Number.isFinite(value)) return true;
      if (sinceMs && value < sinceMs) return false;
      if (beforeMs && value > beforeMs) return false;
      return true;
    });
  }

  function sortedEmails() {
    const sort = $("#sort").value;
    return [...windowEmails()].sort((a, b) => {
      if (sort === "newest") return timestamp(b) - timestamp(a);
      if (sort === "oldest") return timestamp(a) - timestamp(b);
      const aResult = state.results.get(a.id);
      const bResult = state.results.get(b.id);
      const aPriority = aResult ? (priority[aResult.reply_nature] ?? 4) : -1;
      const bPriority = bResult ? (priority[bResult.reply_nature] ?? 4) : -1;
      return aPriority - bPriority || timestamp(b) - timestamp(a);
    });
  }

  function visibleEmails() {
    const query = $("#search").value.trim().toLowerCase();
    const category = $("#filter-content").value;
    const reply = $("#filter-reply").value;

    return sortedEmails().filter(email => {
      const result = state.results.get(email.id);
      const matchesText = !query || `${email.sender} ${email.subject}`.toLowerCase().includes(query);
      return matchesText &&
        (!category || (result && result.content_category === category)) &&
        (!reply || (result && result.reply_nature === reply));
    });
  }

  function displayDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? value
      : new Intl.DateTimeFormat(DATE_LOCALE, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: TIME_ZONE,
      }).format(date);
  }

  function displayDeadline(candidate) {
    if (candidate.all_day) {
      return new Intl.DateTimeFormat(DATE_LOCALE, {
        dateStyle: "medium",
        timeZone: candidate.timezone || TIME_ZONE,
      }).format(new Date(`${candidate.date}T12:00:00Z`));
    }
    return new Intl.DateTimeFormat(DATE_LOCALE, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: candidate.timezone || TIME_ZONE,
    }).format(new Date(candidate.due_at));
  }

  function dateKey(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  // "Today" has to come from Singapore, not from the browser's clock zone.
  const singaporeKeyFormatter = new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: TIME_ZONE,
  });

  function singaporeDateKey(date = new Date()) {
    const parts = Object.fromEntries(
      singaporeKeyFormatter.formatToParts(date).map(({ type, value }) => [type, value]),
    );
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function calendarDateLabel(value, options = { dateStyle: "full" }) {
    return new Intl.DateTimeFormat(DATE_LOCALE, { ...options, timeZone: "UTC" })
      .format(new Date(`${value}T12:00:00Z`));
  }

  function calendarTitle(email) {
    const cleaned = (email.subject || "(no subject)")
      .replace(/^\s*#+\s*/, "")
      .replace(/^\s*(?:assignment|exam|examination|quiz|test|announcement)\s+(?:created|updated|published|posted)\s*[-:–—]\s*/i, "")
      .trim() || "(no subject)";
    // The course token is shown separately, so drop a leading code from the
    // title to avoid "[DSS5105] DSS5105 final exam".
    const withoutCode = cleaned
      .replace(/^[A-Z]{2,5}\s?\d{4,5}[A-Z]?\s*[-–—:·]?\s+/i, "")
      .trim();
    return withoutCode || cleaned;
  }

  function courseCode(email) {
    const text = `${email.subject || ""}\n${email.body || ""}\n${email.preview || ""}`;
    return text.match(/\b([A-Z]{2,5})\s?(\d{4,5}[A-Z]?)\b/i)?.slice(1).join("").toUpperCase() || null;
  }

  // Widely spaced hues so two different courses never receive near-identical
  // colors. The stable hash picks a starting slot; collisions are moved to the
  // next free slot within the current course set.
  const COURSE_HUES = [352, 22, 46, 76, 128, 158, 186, 210, 238, 264, 292, 320];
  const COURSE_HUE_GAP = 40;
  const courseColorCache = new Map();

  function courseHash(code) {
    let hash = 2166136261;
    for (const character of code) {
      hash ^= character.charCodeAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function hueGap(a, b) {
    const distance = Math.abs(a - b) % 360;
    return Math.min(distance, 360 - distance);
  }

  function refreshCourseColors() {
    const codes = [...new Set(
      state.emails.filter(isCanvasEmail).map(courseCode).filter(Boolean),
    )].sort();
    const used = new Set();
    courseColorCache.clear();
    for (const code of codes) {
      const preferred = courseHash(code) % COURSE_HUES.length;
      let chosen = null;
      let fallback = null;
      let fallbackGap = -1;
      for (let step = 0; step < COURSE_HUES.length; step++) {
        const hue = COURSE_HUES[(preferred + step) % COURSE_HUES.length];
        if (used.has(hue)) continue;
        const gap = used.size
          ? Math.min(...[...used].map(other => hueGap(hue, other)))
          : 360;
        if (gap >= COURSE_HUE_GAP) {
          chosen = hue;
          break;
        }
        if (gap > fallbackGap) {
          fallbackGap = gap;
          fallback = hue;
        }
      }
      // More courses than comfortably spaced hues: take the most distant free
      // hue instead of reusing a color.
      const hue = chosen ?? fallback ?? COURSE_HUES[preferred];
      used.add(hue);
      courseColorCache.set(code, hue);
    }
  }

  function courseColor(code) {
    if (!code) return "";
    if (!courseColorCache.has(code)) {
      courseColorCache.set(code, COURSE_HUES[courseHash(code) % COURSE_HUES.length]);
    }
    const hue = courseColorCache.get(code);
    return `--course-bg:hsl(${hue} 82% 92%);--course-border:hsl(${hue} 64% 54%);--course-text:hsl(${hue} 68% 24%);--course-accent:hsl(${hue} 72% 38%)`;
  }

  function courseToken(email) {
    const code = courseCode(email);
    return code ? el("span", { class: "course-token", title: `Course ${code}` }, code) : null;
  }

  // The NUS calendar is independent of the mailbox: term dates, reading and
  // exam weeks, holidays, and vacations provide context for Canvas deadlines.
  function academicTone(category) {
    const text = String(category || "").toLowerCase();
    if (text.includes("holiday")) return "holiday";
    if (text.includes("exam")) return "exam";
    if (text.includes("reading")) return "reading";
    if (text.includes("vacation")) return "vacation";
    if (text.includes("orientation")) return "orientation";
    return "semester";
  }

  function academicRangeLabel(event) {
    if (event.start_date === event.end_date) {
      return calendarDateLabel(event.start_date, {
        weekday: "short",
        day: "numeric",
        month: "short",
        year: "numeric",
      });
    }
    const start = calendarDateLabel(event.start_date, { day: "numeric", month: "short" });
    const end = calendarDateLabel(event.end_date, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
    return `${start} – ${end}`;
  }

  function academicEventCard(event, index) {
    const tone = academicTone(event.category);
    const item = el("article", {
      class: `academic-item academic-item--${tone}`,
      id: `academic-event-${event.start_date}-${index}`,
    });
    const info = el("div", { class: "academic-info" });
    info.append(el("span", { class: "academic-dates" }, academicRangeLabel(event)));
    if (event.notes) {
      info.append(el("span", { class: "academic-notes", title: event.notes }, `· ${event.notes}`));
    }
    item.append(
      el("strong", { class: "academic-title", title: event.event }, event.event),
      info,
    );
    return item;
  }

  function academicShortTitle(event) {
    // The bottom-of-cell label is only a few pixels wide, so keep the useful
    // part ("1A Exam") and leave the full name to the panel and tooltip.
    return event.event
      .replace(/^Mini Semester\s+/i, "")
      .replace(/\bExamination\b/gi, "Exam")
      .replace(/\bVacation\b/gi, "Vac")
      .replace(/^Semester\s+(\d)/i, "Sem $1")
      .replace(/^Special Term Part\s+/i, "Special Term ");
  }

  function academicDayLabel(event, boundary) {
    const tone = academicTone(event.category);
    const title = academicShortTitle(event);
    const text = boundary === "start"
      ? `↦ ${title}`
      : boundary === "end"
        ? `${title} ↤`
        : title;
    const position = boundary === "start" ? " — starts" : boundary === "end" ? " — ends" : "";
    return el("span", {
      class: `academic-day-label academic-day-label--${tone}`,
      title: `${event.event}${position} — ${academicRangeLabel(event)}${event.notes ? ` — ${event.notes}` : ""}`,
    }, text);
  }

  function renderAcademicCalendar(monthStart) {
    const container = $("#academic-events");
    if (!container) return;
    const source = $("#academic-source");
    if (source) {
      source.textContent = state.academicLabel;
      source.hidden = !state.academicLabel;
    }
    const monthStartKey = dateKey(monthStart);
    const monthEndKey = dateKey(
      new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0),
    );
    const events = state.academicEvents
      .filter(event => event.start_date <= monthEndKey && event.end_date >= monthStartKey)
      .sort((a, b) => (
        a.start_date.localeCompare(b.start_date) || a.event.localeCompare(b.event)
      ));
    const count = $("#academic-count");
    if (count) {
      count.hidden = !events.length;
      count.textContent = `${events.length} ${events.length === 1 ? "event" : "events"}`;
    }
    container.replaceChildren();
    if (!events.length) {
      const message = !state.academicLoaded
        ? "Loading the NUS academic calendar…"
        : state.academicEvents.length
          ? "No NUS academic events in this month."
          : "The NUS academic calendar is not available.";
      container.append(el("p", { class: "academic-empty" }, message));
      return;
    }
    events.forEach((event, index) => container.append(academicEventCard(event, index)));
  }

  // Canvas notifications end with a link such as
  // "View assignment | Update your notification settings" or
  // "View announcement | ...". That link says what the message really is, so
  // trust it before guessing from words elsewhere in the body.
  function canvasNotificationKind(text) {
    const match = text.match(/\bview\s+(assignment|announcement|discussion|quiz|exam(?:ination)?)\b/i);
    if (!match) return null;
    const kind = match[1].toLowerCase();
    if (kind === "quiz" || kind.startsWith("exam")) return "exam";
    if (kind === "discussion") return "event";
    return kind;
  }

  // The calendar is for Canvas coursework, so ignore ordinary mail even when
  // its body happens to contain a date.
  function isCanvasEmail(email) {
    if (/canvas|instructure\.com/i.test(email.sender || "")) return true;
    const text = `${email.subject || ""}\n${email.body || ""}\n${email.preview || ""}`;
    return Boolean(canvasNotificationKind(text));
  }

  function calendarEmails(emails = windowEmails()) {
    // The calendar is an assignment list: Canvas announcements, quizzes, and
    // exams stay out even when they contain an explicit date.
    return emails.filter(email =>
      email.deadline_candidate &&
      isCanvasEmail(email) &&
      deadlineKind(email) === "assignment");
  }

  // Label each date by what it is, so a month cell says "assignment" instead of
  // a generic "due". Exams come from the extractor, Canvas link text wins over
  // keyword guesses, and everything else is inferred from the wording.
  function deadlineKind(email) {
    if (email.deadline_candidate.event_type === "exam") return "exam";
    const text = `${email.subject || ""}\n${email.body || ""}\n${email.preview || ""}`;
    const canvasKind = canvasNotificationKind(text);
    if (canvasKind) return canvasKind;
    if (/\b(?:assignment|homework|coursework|submission|submit|essay|report|lab|project|problem\s+set|deliverable|worksheet)\b/i.test(text)) {
      return "assignment";
    }
    return "event";
  }

  function deadlineSortKey(email) {
    const candidate = email.deadline_candidate;
    return candidate.due_at || `${candidate.date}T23:59:59`;
  }

  function deadlineTime(candidate) {
    return candidate.all_day
      ? "All day"
      : new Intl.DateTimeFormat(DATE_LOCALE, {
        timeStyle: "short",
        timeZone: candidate.timezone || TIME_ZONE,
      }).format(new Date(candidate.due_at));
  }

  function deadlineDayLabel(key) {
    const today = singaporeDateKey();
    const tomorrow = singaporeDateKey(new Date(Date.now() + 86400000));
    const formatted = calendarDateLabel(key, {
      weekday: "short",
      day: "numeric",
      month: "short",
    });
    if (key === today) return { name: "Today", date: formatted };
    if (key === tomorrow) return { name: "Tomorrow", date: formatted };
    return { name: formatted, date: "" };
  }

  function deadlineListItem(email) {
    const candidate = email.deadline_candidate;
    const code = courseCode(email);
    const kind = deadlineKind(email);
    const item = el("article", { class: "calendar-item", style: courseColor(code) });
    const main = el("button", {
      class: "calendar-item-main",
      type: "button",
      "aria-label": `${code ? `${code}, ` : ""}${calendarTitle(email)}, ${kind} ${displayDeadline(candidate)}`,
    });
    const meta = el("span", { class: "calendar-item-meta" });
    const badge = courseToken(email);
    if (badge) meta.append(badge);
    main.append(
      meta,
      el("strong", { class: "calendar-item-title" }, calendarTitle(email)),
      el("span", { class: "calendar-item-sub" }, deadlineTime(candidate)),
    );
    main.addEventListener("click", () => selectCalendarEvent(email));
    item.append(main);
    return item;
  }

  function renderCalendar() {
    const grid = $("#calendar-grid");
    if (!grid) return;
    const events = calendarEmails()
      .sort((a, b) => deadlineSortKey(a).localeCompare(deadlineSortKey(b)));
    const count = $("#calendar-upcoming-count");
    if (count) {
      count.hidden = !events.length;
      count.textContent = `${events.length} ${events.length === 1 ? "item" : "items"}`;
    }
    if (!state.selectedCalendarDate) {
      state.selectedCalendarDate = events[0]?.deadline_candidate.date || singaporeDateKey();
    }
    if (!state.calendarMonth) {
      const [year, month] = state.selectedCalendarDate.split("-").map(Number);
      state.calendarMonth = new Date(year, month - 1, 1);
    }
    const monthStart = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth(), 1);
    $("#calendar-month").textContent = new Intl.DateTimeFormat(DATE_LOCALE, {
      month: "long",
      year: "numeric",
    }).format(monthStart);
    grid.replaceChildren();
    const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    weekdays.forEach(day => grid.append(el("div", {
      class: "calendar-weekday",
      role: "columnheader",
      "aria-label": day,
    }, day.slice(0, 3))));

    const eventsByDate = new Map();
    const academicByDate = new Map();
    // The legend lists every course the student is taking, not only courses
    // with a deadline this month. Canvas announcements (which have no deadline
    // candidate) are included when they carry a course code.
    const courses = new Map();
    for (const email of state.emails) {
      if (!isCanvasEmail(email)) continue;
      const code = courseCode(email);
      if (code) courses.set(code, courseColor(code));
    }
    for (const email of events) {
      const key = email.deadline_candidate.date;
      if (!eventsByDate.has(key)) eventsByDate.set(key, []);
      eventsByDate.get(key).push(email);
      const code = courseCode(email);
      if (code) courses.set(code, courseColor(code));
    }
    for (const event of state.academicEvents) {
      const entries = event.start_date === event.end_date
        ? [{ event, boundary: "single" }]
        : event.mark
          ? [
            { event, boundary: "start" },
            { event, boundary: "end" },
          ]
          : [{ event, boundary: "start" }];
      for (const entry of entries) {
        const key = entry.boundary === "end" ? event.end_date : event.start_date;
        if (!academicByDate.has(key)) academicByDate.set(key, []);
        academicByDate.get(key).push(entry);
      }
    }
    const legend = $("#calendar-course-legend");
    legend.replaceChildren();
    $("#calendar-legend-section").hidden = courses.size === 0;
    for (const [code, color] of [...courses].sort(([a], [b]) => a.localeCompare(b))) {
      const item = el("span", { class: "calendar-course-key", style: color });
      item.append(el("span", { class: "course-token" }, code));
      legend.append(item);
    }
    if (events.length && events.some(email => !courseCode(email))) {
      legend.append(el("span", { class: "calendar-course-key calendar-course-unknown" }, "No course detected"));
    }

    const first = new Date(monthStart);
    first.setDate(first.getDate() - ((first.getDay() + 6) % 7));
    const today = singaporeDateKey();
    for (let offset = 0; offset < 42; offset++) {
      const day = new Date(first);
      day.setDate(first.getDate() + offset);
      const key = dateKey(day);
      const dayEvents = eventsByDate.get(key) || [];
      const dayAcademic = academicByDate.get(key) || [];
      const isSelected = key === state.selectedCalendarDate
        && day.getMonth() === monthStart.getMonth();
      const cell = el("div", {
        class: [
          "calendar-day",
          day.getMonth() === monthStart.getMonth() ? "current-month" : "other-month",
          key === today ? "today" : "",
          isSelected ? "selected" : "",
          dayEvents.length ? "has-events" : "",
          dayAcademic.length ? "has-academic" : "",
        ].filter(Boolean).join(" "),
        role: "gridcell",
        "aria-selected": String(isSelected),
      });
      const dayButton = el("button", {
        class: "calendar-day-number",
        type: "button",
        "aria-label": [
          calendarDateLabel(key),
          ...dayAcademic
            .filter(entry => entry.boundary !== "middle")
            .map(entry => {
              const position = entry.boundary === "start"
                ? " starts"
                : entry.boundary === "end"
                  ? " ends"
                  : "";
              return `${entry.event.event}${position}`;
            }),
        ].join(", "),
        "aria-pressed": String(isSelected),
      }, String(day.getDate()));
      dayButton.addEventListener("click", () => {
        state.selectedCalendarDate = key;
        if (day.getMonth() !== monthStart.getMonth()) {
          state.calendarMonth = new Date(day.getFullYear(), day.getMonth(), 1);
        }
        renderCalendar();
        requestAnimationFrame(() => {
          document.getElementById(`calendar-date-${key}`)?.scrollIntoView({
            block: "start",
            behavior: "smooth",
          });
        });
      });
      cell.append(dayButton);
      const dayItems = el("div", { class: "calendar-day-events" });
      dayEvents.slice(0, 2).forEach(email => {
        const candidate = email.deadline_candidate;
        const code = courseCode(email);
        const kind = deadlineKind(email);
        const meta = el("span", { class: "calendar-event-chip-meta" });
        meta.append(
          el("span", { class: "calendar-event-chip-dot", "aria-hidden": "true" }),
          el("span", { class: "calendar-event-chip-title" }, calendarTitle(email)),
        );
        const eventButton = el("button", {
          class: "calendar-event-chip",
          type: "button",
          style: courseColor(code),
          title: `${code ? `[${code}] ` : ""}${calendarTitle(email)} — ${kind} ${displayDeadline(candidate)} — ${candidate.text}`,
          "aria-label": `${code ? `${code}, ` : ""}${calendarTitle(email)}, ${kind} ${displayDeadline(candidate)}, matched ${candidate.text}`,
        });
        eventButton.append(meta);
        eventButton.addEventListener("click", () => {
          state.selectedCalendarDate = key;
          selectCalendarEvent(email);
        });
        dayItems.append(eventButton);
      });
      if (dayEvents.length > 2) {
        dayItems.append(el("span", { class: "calendar-more" }, `+${dayEvents.length - 2} more`));
      }
      cell.append(dayItems);
      if (dayAcademic.length) {
        const academicItems = el("div", { class: "calendar-academic-day" });
        dayAcademic.slice(0, 2).forEach(entry => {
          academicItems.append(academicDayLabel(entry.event, entry.boundary));
        });
        if (dayAcademic.length > 2) {
          academicItems.append(el(
            "span",
            { class: "academic-day-more" },
            `+${dayAcademic.length - 2}`,
          ));
        }
        cell.append(academicItems);
      }
      grid.append(cell);
    }

    renderAcademicCalendar(monthStart);

    const container = $("#calendar-events");
    container.replaceChildren();
    if (!events.length) {
      const empty = el("div", { class: "calendar-empty" });
      if (!state.hasFetchedEmails) {
        empty.append(
          el("strong", {}, "Nothing here yet"),
          el("p", {}, "Load your mailbox and we will pull out Canvas assignment deadlines."),
        );
      } else {
        empty.append(
          el("strong", {}, "No Canvas assignments found"),
          el("p", {}, "Canvas assignment notifications with an explicit due date appear here."),
        );
      }
      container.append(empty);
      return;
    }

    const groups = new Map();
    for (const email of events) {
      const key = email.deadline_candidate.date;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(email);
    }
    for (const [key, items] of groups) {
      const group = el("section", {
        class: "calendar-day-group",
        id: `calendar-date-${key}`,
      });
      const heading = el("h3", { class: "calendar-day-heading" });
      const label = deadlineDayLabel(key);
      heading.append(el("span", { class: "calendar-day-name" }, label.name));
      if (label.date) heading.append(el("span", { class: "calendar-day-date" }, label.date));
      heading.append(el(
        "span",
        { class: "calendar-day-count" },
        `${items.length} ${items.length === 1 ? "item" : "items"}`,
      ));
      group.append(heading);
      for (const email of items) group.append(deadlineListItem(email));
      container.append(group);
    }
  }

  let pushedRefreshTimer = null;
  let pushedRefreshBusy = false;

  function stopPushedRefresh() {
    if (pushedRefreshTimer) {
      clearInterval(pushedRefreshTimer);
      pushedRefreshTimer = null;
    }
    for (const timer of backfillTimers) clearTimeout(timer);
    backfillTimers = [];
  }

  function currentProvider() {
    return $("#provider")?.value || "";
  }

  function describeWebhookAttempt(data) {
    if (!data.configured) {
      return "Mail receiving is not configured. Set POWER_AUTOMATE_WEBHOOK_TOKEN in .env.";
    }
    const attempt = (data.attempts || [])[0];
    if (!attempt) return "Last mail: none yet.";
    const when = new Date(attempt.at).toLocaleTimeString(DATE_LOCALE, {
      timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    if (attempt.status === 200) {
      let verdict = attempt.owner
        ? `stored for ${attempt.owner}`
        : "stored without an owner";
      if (attempt.path !== "/api/inbound/outlook") verdict += " · check the flow URI";
      return `Last mail: ${when} — ${verdict}`;
    }
    const reasons = {
      400: "unreadable request",
      401: "token mismatch",
      405: "wrong URL path",
      503: "no webhook token configured",
    };
    return `Last attempt: ${when} — ${reasons[attempt.status] || `rejected with ${attempt.status}`}`;
  }

  async function refreshWebhookDiagnostics() {
    const box = $("#webhook-diag");
    if (!box) return;
    try {
      const data = await api("/api/inbound/diagnostics", undefined, { timeoutMs: 8000 });
      box.textContent = describeWebhookAttempt(data);
      refreshTriggerReady = Boolean(data.refresh_configured);
      if (!refreshTriggerReady) {
        setBackfillStatus(
          "Automatic flow trigger is off. Set POWER_AUTOMATE_REFRESH_URL in .env to turn it on.",
        );
      }
      // Wait for this check so a missing trigger URL stays silent instead of
      // showing an error on every page load. Only nudge the flow after the
      // person has confirmed their mailbox at the gate.
      if (refreshTriggerReady && !backfillKickoff && state.userReady) {
        backfillKickoff = true;
        requestBackfill({ force: true });
      }
    } catch (error) {
      // Keep the previous line; the next tick retries.
    }
  }

  async function refreshPushedInbox() {
    if (pushedRefreshBusy || state.controller) return;
    if (document.visibilityState === "hidden") return;
    if (currentProvider() !== "powerautomate" || !currentUser()) return;
    pushedRefreshBusy = true;
    try {
      const data = await api("/api/emails", {
        provider: "powerautomate",
        credentials: {},
        count: readCount(state.taxonomy?.max_emails),
      }, { timeoutMs: 30000 });
      state.emails = data.emails;
      state.hasFetchedEmails = true;
      state.loadError = null;
      if (state.emails.length) setGoLabel("Start classification");
      updateSummary();
      renderRows();
      if (!state.selectedId && state.emails.length) {
        state.selectedId = state.emails[0].id;
        renderDetail(state.emails[0]);
      }
    } catch (error) {
      // Offline or the flow is idle; the next tick retries.
    } finally {
      pushedRefreshBusy = false;
    }
  }


  function startPushedRefresh() {
  stopPushedRefresh();

  pushedRefreshTimer = setInterval(
    refreshPushedInbox,
    5000,
  );
}

  function startWebhookDiagnostics() {
    refreshWebhookDiagnostics();
    setInterval(refreshWebhookDiagnostics, 15000);
  }

  // The flow only runs on a schedule, so the dashboard nudges it once after the
  // person identifies themselves. The time window only filters loaded mail.
  // The trigger URL is a secret, so the browser asks our server to call it.
  let backfillRequestAt = 0;
  let backfillRequestKey = "";
  let refreshTriggerReady = false;
  let backfillKickoff = false;

  let backfillHideTimer = null;
  let backfillTimers = [];

  function setBackfillStatus(text, isError = false, hideAfter = 0) {
    const box = $("#backfill-status");
    if (!box) return;
    clearTimeout(backfillHideTimer);
    box.textContent = text || "";
    box.hidden = !text;
    box.classList.toggle("err", Boolean(text) && isError);
    if (text && hideAfter) {
      backfillHideTimer = setTimeout(() => setBackfillStatus(""), hideAfter);
    }
  }

  async function requestBackfill({ force = false } = {}) {
    if (!refreshTriggerReady) return;
    if (currentProvider() !== "powerautomate" || !currentUser()) return;
    // The time window filters mail that is already loaded, so ask the flow for
    // the newest batch without narrowing its search to a window.
    const key = currentUser();
    const now = Date.now();
    // A change of person always goes through; repeat visits wait a minute so a
    // reload does not spawn several flow runs.
    if (!force && key === backfillRequestKey && now - backfillRequestAt < 60000) return;
    backfillRequestKey = key;
    backfillRequestAt = now;
    setBackfillStatus("Asking the Power Automate flow for the latest mail…");
    try {
      // Give the flow a wide lower bound so loading 100 messages is not
      // limited by the narrower display window chosen in the toolbar.
      const since = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString();
      await api("/api/inbound/refresh", { since }, { timeoutMs: 20000 });
      setBackfillStatus("Checking for new mail…", false, 5000);
      // A fresh request replaces the old follow-up checks instead of stacking
      // another set on every user switch.
      for (const timer of backfillTimers) clearTimeout(timer);
      backfillTimers = [5000, 15000, 30000, 60000].map(delay =>
        setTimeout(refreshPushedInbox, delay));
    } catch (error) {
      setBackfillStatus(`Could not trigger the flow: ${error.message}`, true);
    }
  }

  function showDashboardTab(tab) {
    const calendarActive = tab === "calendar";
    $("#inbox-panel").hidden = calendarActive;
    $("#calendar-panel").hidden = !calendarActive;
    $("#inbox-tab").classList.toggle("active", !calendarActive);
    $("#calendar-tab").classList.toggle("active", calendarActive);
    $("#inbox-tab").setAttribute("aria-selected", String(!calendarActive));
    $("#calendar-tab").setAttribute("aria-selected", String(calendarActive));
  }

  function selectEmail(email) {
    state.selectedId = email.id;
    renderRows();
    renderDetail(email);
  }

  function selectCalendarEvent(email) {
    state.selectedCalendarDate = email.deadline_candidate.date;
    const date = new Date(`${state.selectedCalendarDate}T12:00:00`);
    state.calendarMonth = new Date(date.getFullYear(), date.getMonth(), 1);
    renderCalendar();
    renderDetail(email);
    if (!$("#email-detail-dialog").open) $("#email-detail-dialog").showModal();
  }

  function openEmail(email) {
    selectEmail(email);
    if (!$("#email-detail-dialog").open) $("#email-detail-dialog").showModal();
  }

  function hasActiveFilters() {
    return Boolean(
      $("#search").value.trim() ||
      $("#filter-content").value ||
      $("#filter-reply").value
    );
  }

  function activeFilterCount() {
    let count = 0;
    if ($("#search").value.trim()) count += 1;
    if ($("#filter-content").value) count += 1;
    if ($("#filter-reply").value) count += 1;
    return count;
  }

  function resetFilters() {
    $("#search").value = "";
    $("#filter-content").value = "";
    $("#filter-reply").value = "";
    setQuickFilter("all");
    $("#search").focus();
  }

  function emptyRow({ icon = "✉", title, text, actionLabel, onAction }) {
    const box = el("div", { class: "v2-empty" });
    box.append(
      el("span", { class: "v2-empty-icon", "aria-hidden": "true" }, icon),
      el("strong", {}, title),
      el("p", {}, text),
    );
    if (actionLabel && onAction) {
      const action = el("button", { type: "button", class: "v2-empty-action" }, actionLabel);
      action.addEventListener("click", onAction);
      box.append(action);
    }
    const cell = el("td", { class: "table-empty", colspan: "5" });
    cell.append(box);
    const row = el("tr");
    row.append(cell);
    return row;
  }

  function renderRows() {
    const body = $("#email-rows");
    const emails = visibleEmails();
    const filtersActive = hasActiveFilters();
    body.replaceChildren();

    $("#clear-filters").hidden = !filtersActive;
    const filterButton = $("#filter-toggle");
    if (filterButton) {
      filterButton.textContent = filtersActive ? `Filters (${activeFilterCount()})` : "Filters";
    }

    if (state.loading) {
      const loading = el("div", { class: "v2-loading" });
      loading.append(
        el("span", { class: "v2-spinner", "aria-hidden": "true" }),
        el("span", {}, "Fetching your mail…"),
      );
      const cell = el("td", { class: "table-empty", colspan: "5" });
      cell.append(loading);
      const row = el("tr");
      row.append(cell);
      body.append(row);
      $("#results-count").textContent = "Loading…";
      return;
    }

    if (!emails.length) {
      let empty;
      if (state.loadError) {
        empty = {
          icon: "!",
          title: "Could not load mail",
          text: state.loadError,
          actionLabel: "Try again",
          onAction: () => loadEmails({ announce: true }),
        };
      } else if (state.emails.length) {
        empty = {
          icon: "⌕",
          title: "No matching mail",
          text: "Try a different search, or clear the filters to see everything again.",
          actionLabel: "Clear filters",
          onAction: resetFilters,
        };
      } else if (currentProvider() === "powerautomate") {
        empty = {
          icon: "✉",
          title: "Waiting for mail",
          text: "New messages appear here automatically after your Power Automate flow sends them.",
          actionLabel: "Refresh",
          onAction: () => loadEmails({ announce: true }),
        };
      } else {
        empty = {
          icon: "✉",
          title: "Nothing fetched yet",
          text: "Fetch your inbox to see what needs attention.",
          actionLabel: "Fetch mail",
          onAction: () => loadEmails({ announce: true }),
        };
      }
      body.append(emptyRow(empty));
      $("#results-count").textContent = "";
      return;
    }

    const total = state.emails.length;
    $("#results-count").textContent = emails.length === total
      ? `${total} email${total === 1 ? "" : "s"}`
      : `${emails.length} of ${total} emails`;

    for (const email of emails) {
      const result = state.results.get(email.id);
      const row = el("tr", { class: email.id === state.selectedId ? "selected" : "" });
      const details = el("td", { class: "dashboard-email-cell" });
      const select = el("button", {
        type: "button",
        class: "email-select",
        "aria-pressed": String(email.id === state.selectedId),
      });
      select.append(
        el("strong", {}, email.subject || "(no subject)"),
        el("small", {}, displayDate(email.received)),
      );
      select.addEventListener("click", () => openEmail(email));
      details.append(select);

      const sender = el("td", { class: "dashboard-sender-cell", "data-label": "From" });
      sender.append(el(
        "span",
        { class: "sender-name", title: email.sender || "Unknown sender" },
        email.sender || "Unknown sender",
      ));

      let category = el("span", { class: "sub" }, "Classifying…");
      let reply = el("span", { class: "sub" }, "—");
      if (result?.error) {
        category = el("span", { class: "dashboard-error", title: result.error }, "Failed");
        reply = el("span", { class: "sub" }, "Retry by fetching again");
      } else if (result) {
        category = tagFor(state.taxonomy, "content", result.content_category);
        reply = tagFor(state.taxonomy, "reply", result.reply_nature);
      } else {
        category = el("span", { class: "sub" }, "Not classified");
      }
      const categoryCell = el("td", { "data-label": "Category" });
      const replyCell = el("td", { "data-label": "Status" });
      categoryCell.append(category);
      replyCell.append(reply);
      row.append(
        details,
        sender,
        categoryCell,
        replyCell,
        el("td", { class: "row-open", "aria-hidden": "true" }, "›"),
      );
      row.addEventListener("click", event => {
        if (event.target.closest("button, a, input, select, textarea")) return;
        openEmail(email);
      });
      body.append(row);
    }
  }

  function renderDetail(email) {
    const box = $("#email-detail");
    const course = email.deadline_candidate ? courseCode(email) : null;
    $("#email-detail-title").textContent = email.deadline_candidate
      ? `${email.deadline_candidate.event_type === "exam" ? "Exam details" : "Deadline details"}${course ? ` · ${course}` : ""}`
      : email.subject || "(no subject)";
    box.replaceChildren(
      el("p", { class: "detail-sender" }, email.sender || "Unknown sender"),
      el("p", { class: "sub" }, displayDate(email.received)),
    );
    if (email.deadline_candidate && calendarTitle(email) !== (email.subject || "(no subject)")) {
      box.append(el("p", { class: "sub" }, `Email subject: ${email.subject}`));
    }
    if (email.deadline_candidate) {
      const candidate = email.deadline_candidate;
      const kind = deadlineKind(email);
      const deadline = el("section", {
        class: "deadline-popup",
        style: courseColor(course),
      });
      const head = el("div", { class: "deadline-head" });
      const badge = courseToken(email);
      if (badge) head.append(badge);
      head.append(el(
        "p",
        { class: "calendar-event-date" },
        `${kind[0].toUpperCase()}${kind.slice(1)} ${displayDeadline(candidate)}`,
      ));
      deadline.append(
        head,
        el("p", { class: "calendar-evidence" }, `Matched text: “${candidate.text}”`),
      );
      if (candidate.year_inferred) {
        deadline.append(el("p", { class: "calendar-warning" }, "The year was inferred from the received date. Verify it before adding."));
      }
      box.append(deadline);
    }
    const body = email.body || email.preview || "(No email body available.)";
    if (email.text_source && email.text_source !== "body") {
      const confidence = email.ocr_confidence == null
        ? ""
        : ` (${email.ocr_confidence}% OCR confidence)`;
      box.append(el("p", { class: "sub" }, `Text source: ${email.text_source}${confidence}`));
    }
    for (const note of email.ocr_notes || []) {
      box.append(el("p", { class: "sub" }, note));
    }
    box.append(el("h3", {}, "Message"), el("pre", { class: "detail-body" }, body));
  }

  async function refreshHealth() {
    const backend = $("#backend").value;
    const pill = $(".v2-health");
    try {
      const health = await api(`/api/health?backend=${encodeURIComponent(backend)}`, undefined, { timeoutMs: 10000 });
      const isReady = health.backend_ready;
      $("#dot").className = `dot ${isReady === true ? "ok" : isReady === false ? "bad" : ""}`;
      const detail = isReady === true
        ? `${backendLabel(backend)} ready · ${ocrStatusLabel(health.ocr)}`
        : isReady === false && backend === "ml"
          ? "Classical ML models not found. Train them with: PYTHONPATH=../classical-ml/src .venv/bin/python -m train_email_ml"
          : isReady === false && backend === "hybrid"
            ? "Hybrid needs the classical-ML category model and the BERT action head. See README: Choosing a backend."
            : isReady === false ? `${backendLabel(backend)} is not ready.` : "Backend readiness unknown.";
      $("#health").textContent = isReady === true ? "Ready" : isReady === false ? "Not ready" : "Checking…";
      pill.classList.toggle("bad", isReady === false);
      pill.title = detail;
    } catch (error) {
      $("#dot").className = "dot bad";
      $("#health").textContent = "Offline";
      pill.classList.add("bad");
      pill.title = error.message || "Could not check backend status.";
    }
  }

  async function loadEmails({ forCalendar = false, announce = false } = {}) {
    const { provider, credentials } = readCredentials();
    const invalid = validateCredentials(provider);
    if (invalid) {
      notice(invalid.msg, true);
      $(invalid.focus).focus();
      return;
    }

    const controller = new AbortController();
    state.controller = controller;
    if (provider !== "powerautomate") stopPushedRefresh();
    state.emails = [];
    state.results.clear();
    state.hasFetchedEmails = false;
    state.calendarSignature = null;
    setCalendarStatus("");
    state.selectedId = null;
    state.loading = true;
    state.loadError = null;
    setGoLabel("Load emails");
    if ($("#email-detail-dialog").open) $("#email-detail-dialog").close();
    notice("");
    updateSummary();
    renderRows();
    $("#email-detail").replaceChildren(el("p", { class: "empty" }, "Loading emails…"));
    setProgress(0, 0);
    setBusy(true, "Loading…");

    try {
      // Loading and classification are separate steps: fetch the newest batch
      // once, then let the person narrow the time window before classifying.
      const data = await api("/api/emails", {
        provider,
        credentials,
        count: readCount(state.taxonomy?.max_emails),
      }, { signal: controller.signal, timeoutMs: 60000 });
      state.emails = data.emails;
      state.hasFetchedEmails = true;
      state.loading = false;
      state.selectedCalendarDate = null;
      state.calendarMonth = null;
      setGoLabel(state.emails.length ? "Start classification" : "Load emails");
      updateSummary();
      if (provider === "powerautomate") startPushedRefresh();
      if (!state.emails.length) {
        renderRows();
        $("#email-detail").replaceChildren(el("p", { class: "empty" }, "No emails found."));
        const empty = provider === "powerautomate"
          ? "No pushed mail yet. New messages appear here after the flow sends them."
          : "No emails found in your mailbox.";
        if (forCalendar) setCalendarStatus(provider === "powerautomate" ? "No pushed mail yet" : "No emails found");
        else notice(empty);
        return;
      }

      const firstVisible = windowEmails()[0] || state.emails[0];
      state.selectedId = firstVisible.id;
      renderRows();
      renderDetail(firstVisible);
      if (forCalendar) {
        const count = calendarEmails().length;
        setCalendarStatus(count
          ? `${count} date${count === 1 ? "" : "s"} found`
          : "No dates found");
      } else if (announce) {
        const loaded = state.emails.length;
        notice(`Loaded ${loaded} email${loaded === 1 ? "" : "s"}. Choose a time window, then press Start classification.`);
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        state.loadError = error.message;
        if (forCalendar) setCalendarStatus(`Scan failed: ${error.message}`, true);
        else notice(error.message, true);
      }
    } finally {
      state.loading = false;
      if (state.controller === controller) {
        state.controller = null;
        setBusy(false);
        setProgress(0, 0);
      }
      renderRows();
    }
  }

  async function classifyLoaded() {
    const emails = windowEmails();
    if (!emails.length) {
      notice("No emails in this time window. Choose a longer window or load mail first.", true);
      return;
    }

    const controller = new AbortController();
    state.controller = controller;
    for (const email of emails) state.results.delete(email.id);
    notice("");
    setBusy(true, "Classifying…");
    setProgress(0, emails.length);

    let failures = 0;
    let showDone = false;
    try {
      for (let index = 0; index < emails.length; index++) {
        if (controller.signal.aborted) break;
        const email = emails[index];
        try {
          const result = await classifyEmail(email, $("#backend").value, controller.signal);
          state.results.set(email.id, result);
        } catch (error) {
          if (controller.signal.aborted) break;
          failures += 1;
          state.results.set(email.id, { error: error.message });
        }
        setProgress(index + 1, emails.length);
        updateSummary();
        renderRows();
        if (state.selectedId === email.id) renderDetail(email);
      }
      if (controller.signal.aborted) {
        notice("Classification stopped.");
      } else {
        setProgressDone(emails.length, failures);
        showDone = true;
        if (failures) {
          notice(`${failures} email${failures === 1 ? "" : "s"} could not be classified.`, true);
        }
      }
    } finally {
      if (state.controller === controller) {
        state.controller = null;
        setBusy(false);
        if (!showDone) setProgress(0, 0);
      }
      renderRows();
    }
  }

  async function scanCalendar() {
    if (!state.hasFetchedEmails) {
      await loadEmails({ forCalendar: true });
      return;
    }
    updateSummary();
    renderCalendar();
    const count = calendarEmails().length;
    setCalendarStatus(count
      ? `${count} date${count === 1 ? "" : "s"} found`
      : "No dates found");
  }

  async function loadAcademicCalendar() {
    try {
      const data = await api("/api/academic-calendar", undefined, { timeoutMs: 10000 });
      state.academicEvents = Array.isArray(data.events) ? data.events : [];
      state.academicLabel = data.label || "";
    } catch (error) {
      // Missing CSV or an offline server should not block the mailbox.
      state.academicEvents = [];
      state.academicLabel = "";
    } finally {
      state.academicLoaded = true;
      renderCalendar();
    }
  }

  async function init() {
    initMailboxForm();
    loadAcademicCalendar();
    $("#go").addEventListener("click", () => (
      state.hasFetchedEmails ? classifyLoaded() : loadEmails({ announce: true })
    ));
    $("#calendar-fetch").addEventListener("click", scanCalendar);
    $(".calendar-empty-scan")?.addEventListener("click", scanCalendar);
    document.addEventListener("userchange", event => {
      // This page swaps mail in place, so the shared helper must not reload.
      event.preventDefault();
      // Stop any fetch or classification still running for the old person
      // before its response can land in the new person's table.
      state.controller?.abort();
      state.controller = null;
      state.userReady = true;
      if (event.detail.previous === event.detail.email && state.hasFetchedEmails) {
        return;
      }
      state.emails = [];
      state.results.clear();
      state.hasFetchedEmails = false;
      state.calendarSignature = null;
      state.selectedId = null;
        state.loading = false;
      state.loadError = null;
      setGoLabel("Load emails");
      if ($("#email-detail-dialog").open) $("#email-detail-dialog").close();
      $("#email-detail").replaceChildren(el("p", { class: "empty" }, "Select an email to view its details."));
      setCalendarStatus("");
      updateSummary();
      renderRows();
      if (currentProvider() === "powerautomate") {
        startPushedRefresh();
        if (refreshTriggerReady) backfillKickoff = true;
        requestBackfill({ force: true });
      }
      loadEmails({ announce: true });
    });
    for (const selector of ["#window", "#since", "#before"]) {
      $(selector)?.addEventListener("change", () => {
        updateSummary();
        renderRows();
      });
    }
    startWebhookDiagnostics();
    $("#cancel").addEventListener("click", () => state.controller?.abort());
    $("#inbox-tab").addEventListener("click", () => showDashboardTab("inbox"));
    $("#calendar-tab").addEventListener("click", () => showDashboardTab("calendar"));
    $("#calendar-previous").addEventListener("click", () => {
      state.calendarMonth = new Date(
        state.calendarMonth.getFullYear(),
        state.calendarMonth.getMonth() - 1,
        1,
      );
      renderCalendar();
    });
    $("#calendar-next").addEventListener("click", () => {
      state.calendarMonth = new Date(
        state.calendarMonth.getFullYear(),
        state.calendarMonth.getMonth() + 1,
        1,
      );
      renderCalendar();
    });
    $("#calendar-today").addEventListener("click", () => {
      state.selectedCalendarDate = singaporeDateKey();
      const [year, month] = state.selectedCalendarDate.split("-").map(Number);
      state.calendarMonth = new Date(year, month - 1, 1);
      renderCalendar();
    });
    $("#email-detail-close").addEventListener("click", () => $("#email-detail-dialog").close());
    $("#email-detail-dialog").addEventListener("click", event => {
      if (event.target === $("#email-detail-dialog")) $("#email-detail-dialog").close();
    });
    $("#email-detail-dialog").addEventListener("cancel", event => {
      event.preventDefault();
      $("#email-detail-dialog").close();
    });
    $("#backend").addEventListener("change", refreshHealth);
    $("#quick-all").addEventListener("click", () => setQuickFilter("all"));
    $("#quick-action").addEventListener("click", () => setQuickFilter("action"));
    $("#quick-reply").addEventListener("click", () => setQuickFilter("reply"));
    $("#clear-filters").addEventListener("click", resetFilters);
    for (const selector of ["#search", "#filter-content", "#filter-reply", "#sort"]) {
      $(selector).addEventListener("input", () => {
        updateQuickButtons("");
        renderRows();
      });
      $(selector).addEventListener("change", () => {
        updateQuickButtons("");
        renderRows();
      });
    }

    const mobileFilters = window.matchMedia("(max-width: 760px)");
    const setAdvancedFilters = open => {
      $("#filter-advanced").hidden = !open;
      $("#filter-toggle").setAttribute("aria-expanded", String(open));
    };
    setAdvancedFilters(!mobileFilters.matches);
    $("#filter-toggle").addEventListener("click", () => {
      setAdvancedFilters($("#filter-advanced").hidden);
    });
    mobileFilters.addEventListener?.("change", event => setAdvancedFilters(!event.matches));

    document.addEventListener("keydown", event => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      const typing = ["input", "textarea", "select"].includes(tag);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        $("#search").focus();
      } else if (event.key === "Escape" && document.activeElement === $("#search")) {
        if ($("#search").value) {
          $("#search").value = "";
          updateQuickButtons("");
          renderRows();
        } else {
          $("#search").blur();
        }
      }
    });
    document.addEventListener("click", event => {
      const settings = $("#v2-settings");
      if (settings?.open && !settings.contains(event.target)) settings.open = false;
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && $("#v2-settings")?.open) $("#v2-settings").open = false;
    });

    try {
      const [taxonomy, backendData] = await Promise.all([
        api("/api/taxonomy"),
        loadBackends(),
      ]);
      state.taxonomy = taxonomy;
      setQuickFilter("all");
      fillOptions($("#filter-content"), taxonomy.content, "All categories");
      fillOptions($("#filter-reply"), taxonomy.reply, "All types");
      $("#backend").replaceChildren(...BACKENDS.map(item =>
        el("option", { value: item.id }, item.label)));
      if (!backendData.backends.length) throw new Error("No classifier backends are available.");
      $("#backend").value = BACKEND_DEFAULT;
      renderRows();
      renderCalendar();
      setCalendarStatus("");
      showDashboardTab(window.location.hash === "#calendar" ? "calendar" : "inbox");
      await refreshHealth();
    } catch (error) {
      notice(error.message, true);
      $("#go").disabled = true;
    }
  }

  init();
})();
