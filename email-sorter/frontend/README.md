# NusBox — React dashboard

The main dashboard. React + TypeScript + Vite + Tailwind, served by Flask at
`/` from `../static/app/`. Without a build, Flask says how
to make one.

## Build and run

```bash
cd email-sorter/frontend
npm install
npm run build      # writes ../static/app/ (git-ignored)

cd ..
../.venv/bin/python run.py --port 5001 --no-tunnel
# open http://127.0.0.1:5001/
```

Live development with hot reload (Flask must be running on port 5001, or set
`FLASK_URL`); Vite proxies `/api`, `/login`, `/logout`:

```bash
npm run dev        # http://127.0.0.1:5173
```

## Data flow

- `src/services/api.ts` — same-origin fetch; redirects to the login page on 401.
- `src/services/flask.ts` — typed calls to `/api/session`, `/api/emails`,
  `/api/classify`, `/api/backends`, `/api/health`, `/api/academic-calendar`,
  and the Power Automate refresh endpoints. Maps Flask payloads to `InboxEmail`.
- `src/hooks/useInboxView.ts` — load, classify (sequential, cancellable),
  5 s polling for pushed mail, time window, filters, and selection.
- Emails exist before classification; deadlines come from the backend's
  date extractor, so the calendar works without running a model.

## Palette

- **NUS Blue** `#003D7C` — primary interactive accent: navigation, focus rings,
  selection, buttons, and links.
- **NUS Orange** `#EF7C00` — secondary highlight: deadline cards, today marker,
  upcoming dates, and the logo edge. Orange is never used for white text; dark
  text sits on orange fills, and darker derived tones are used on orange tints.
- Neutrals are cool, Apple-style grays: page `#F5F5F7`, white surfaces,
  near-black ink `#1D1D1F`, muted text `#6E6E73`, hairline separators
  `#D9D9DE`.

## Visual language

Minimal, Apple-inspired: the SF system font stack, white surfaces with hairline
borders instead of drop shadows, a segmented control for Inbox ⇄ Calendar,
sentence-case field labels, borderless gray chips that fill blue when selected,
and one accent per interaction state.

## Checks

```bash
npm run typecheck
npm run build      # writes ../static/app/
```

Remote access: ngrok tunnels the Flask port, and Flask serves this app, so the
tunnel needs no extra setup. Build first on whichever machine runs Flask.

## Structure

- `src/domain/` — typed `InboxEmail` model, taxonomy mirror, filter/sort logic,
  calendar, academic-calendar and course-color helpers.
- `src/services/` — `api.ts` (same-origin fetch) and `flask.ts` (typed calls and
  payload mapping).
- `src/hooks/` — `useInboxView` (load, classify, poll, filters),
  `useCalendarView` (month grid, deadlines, NUS calendar) and
  `usePersonalEvents` (events the student adds).
- `src/components/` — inbox, calendar and dialog components.

## Calendar

Month view of dates found in emails (read-only), NUS academic calendar dates
(small gray text at the bottom of a day), and personal events the student adds
(saved on the server in `private/events.json`). Nothing is written to a mailbox
or an external calendar.

## Accessibility

- Each view exposes exactly one `h1` (`Inbox` / `Calendar`), with page sections
  under `h2`.
- Every interactive control is at least 44×44 CSS px, including filter chips,
  quick filters, the view switcher, search/sort fields, and the calendar month
  controls.
- All buttons and inputs have accessible names; focus-visible rings use NUS
  Blue; `prefers-reduced-motion` is honoured.
- Verified by an automated DOM audit at 1440×1000 and 390×844 across the default,
  filtered, empty, detail, and calendar states: zero controls under 44 px and no
  horizontal overflow.

## Limitations

- Calendar dates come from a regex extractor, so only explicit dates with a cue
  such as "due" or "exam" are found.
- Personal events have no recurrence, reminders, or external calendar sync.
- The time band is sent to the server (`since`/`before`, at least the last 30 days so Today and Calendar stay filled), up to 500 messages per load.
