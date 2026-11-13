# NusBox app

A Flask backend and a React dashboard (`frontend/`). The app loads a student's
recent email, classifies each message into one **category** and one
**action**, and shows the results on the Today, Inbox, Calendar and course
pages.

The app supports four classifier families (text encoders, classical ML, Llama,
Claude) and two mail sources (a pasted Microsoft Graph token, or mail pushed by
a Power Automate flow).

---

## Setup

Use the shared environment from the repo root:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp email-sorter/.env.example email-sorter/.env
```

Edit `email-sorter/.env` if needed:

| Setting | Default | Meaning |
|---|---|---|
| `MAIL_PROVIDER` | `powerautomate` | `powerautomate` (sign-in; each student picks their flow or a Graph token) or `graphtoken` (no sign-in) |
| `MODEL_BACKEND` | `hybrid_claude` | default classifier backend |
| `PORT` | `5001` | 5000 clashes with macOS AirPlay Receiver (it answers with 403) |
| `MAX_EMAILS` | `500` | load cap per batch |
| `INBOUND_MAX_EMAILS` | `500` | pushed-mail cap per account |
| `FLOW_REFRESH_TOP` | `0` | emails the flow reads per refresh, sent with each refresh (0 = the flow's own default, 300). Changing it needs a restart, not a flow re-import |
| `FLOW_INCREMENTAL` | `1` | after one complete refresh, later refreshes only read newer mail; `0` always reads the whole window |
| `PUSHED_MAIL_FILE` | `private/pushed_mail.json` | where pushed mail is saved so a restart keeps it (empty turns saving off) |
| `CLASSIFICATION_METRICS` | off | set to `1` to log JSON timing lines for each classification |
| `ALLOW_SIGNUP` | `1` | lets new students create their own account at `/register` (Power Automate mode); `0` turns it off |
| `ALLOW_TOKEN_LOGIN` | `1` | sign-in page offers "Use an Outlook token instead": no account, Microsoft Graph checks the token and the allowed email domains apply; `0` turns it off |
| `ALLOWED_EMAIL_DOMAINS` | `u.nus.edu,nus.edu.sg` | only these email domains may sign up |
| `SIGNUP_CODE` | empty | when set, sign-up asks for this code, so only people you share it with can join |
| `SESSION_COOKIE_SECURE` | off | set to `1` when the app is only used over HTTPS (the ngrok URL); Safari will not send the cookie to plain `http://127.0.0.1` |

Run from the repo root:

```bash
python email-sorter/run.py
# open http://127.0.0.1:5001 (with --tunnel, also the ngrok link it prints)
```

`run.py` rebuilds the React app into `static/app/` when `frontend/` has
changed. That needs `npm install` in `frontend/` once; `--no-build` skips it.

---

## Mail sources

The source is fixed at launch with `--provider`; the browser does not ask for a
source.

### Graph token only (no sign-in)

```bash
python email-sorter/run.py --port 5001 --provider graphtoken
```

- No app login is required.
- The dashboard opens a **Graph access token** popup on first load.
- Get a token from [Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer); it needs `Mail.Read`.
- Tokens expire after about an hour; paste a fresh one when asked.
- The token is sent per request and is not stored on disk.

### Power Automate (pushed mail)

```bash
python email-sorter/run.py --port 5001 --provider powerautomate
```

- Adds a per-user login page at `/login` (sign in with the account email and
  the app-only password; no browser Basic-auth popup).
- ngrok is **off by default**, so teammates can just run `python run.py` and
  work locally. The live machine shares the app with `--tunnel` (or
  `USE_NGROK=1` in `.env`) using `agile-problem-luxury.ngrok-free.dev`;
  `--ngrok-domain other.ngrok-free.dev` picks another reserved domain.

Accounts live in `private/multiuser.json` (`MULTIUSER_CONFIG_FILE`), created
empty on the first start. Students create their own account at `/register`
and then see their **webhook token** in the Connect Outlook guide.

To add an account by hand instead (an admin task, not needed for sign-up):

```bash
cd email-sorter
python configure_multiuser.py
```

It asks for the account email, an app-only password (8+ characters) and an
optional Power Automate trigger URL, writes the account with `600`
permissions, and prints its webhook token.

#### Power Automate flow

Students do not need this section: after signing in, **Connect Outlook** (Today page, the account menu, or Ctrl/Cmd+K) opens a step-by-step guide with their own address, headers and token filled in, plus copy buttons.

The guide's **Download my flow** button (`GET /api/setup/flow.zip`) gives each signed-in student a ready-made import package built by `app/mail/flow_package.py` with their own webhook address, email and token. They import it in Power Automate (**My flows > Import > Import Package (Legacy)**), pick their Outlook connection, then paste the flow's trigger **HTTP URL** back into the guide (`POST /api/setup/flow-url`, only `*.logic.azure.com` or `*.powerplatform.com` addresses are accepted). The app then asks that flow for mail each time it opens. Never share your own exported flow .zip: it contains your webhook token.

Build a flow that collects a window of mail and posts each message to the app.
The HTTP action needs a Power Automate premium connector.

```
Recurrence (or When an HTTP request is received)
 └─ Get emails (V3)      Folder=Inbox, Top=200, Unread=No
     └─ Apply to each    input: value
         └─ HTTP         POST https://your-ngrok-domain/api/inbound/outlook
```

Use a bounded search query, for example:

```
concat('received>=', formatDateTime(addDays(utcNow(), -30), 'yyyy-MM-dd'))
```

HTTP action settings:

- Method: `POST`
- URI: `https://your-ngrok-domain/api/inbound/outlook`
- `Content-Type: application/json`
- `X-Webhook-Token: <the account token>`
- `X-User-Email: <the mailbox this flow watches>`
- `ngrok-skip-browser-warning: true` (for free ngrok tunnels)
- Body, inside the loop:

```json
{
  "internetMessageId": "@{item()?['internetMessageId']}",
  "subject": "@{item()?['subject']}",
  "from": "@{item()?['from']}",
  "receivedDateTime": "@{item()?['receivedDateTime']}",
  "bodyPreview": "@{item()?['bodyPreview']}",
  "body": "@{item()?['body']}"
}
```

`Get emails (V3)` returns `from` and `body` as plain strings. The app also
accepts the nested Graph shape.

If the flow omits `X-User-Email`, the app files the message under the webhook
token's account. If the body includes an owner or To recipient that does not
match that account, the push is rejected.

#### Triggering a backfill

A flow that starts with **When an HTTP request is received** can be started by
the dashboard. Paste its HTTP URL into the Connect Outlook guide (it is saved
as the account's `refresh_url`; no restart needed). The trigger body may
include:

```json
{
  "owner": "you@u.nus.edu",
  "since": "2026-09-28T00:00:00Z",
  "before": "2026-10-28T23:59:59Z"
}
```

After signing in, the dashboard asks the flow for the latest mail once.
Changing **Time window** only filters mail that is already loaded.

#### Notes

- Pushed mail keeps the newest 500 per account by default and is saved to
  `private/pushed_mail.json`, so a restart keeps it.
- Duplicate message ids are ignored per person.
- HTML bodies are converted to text; attachments are not processed by this path.
- Only `POST /api/inbound/outlook` accepts pushes. Opening it in a browser
  returns `405`.
- Keep the ngrok URL and tokens private. Stop the flow when you are done; the
  cloud flow keeps running even if the app is stopped, and pushes sent while the
  app is down are rejected.

---

## Several people, one app

- `--provider graphtoken`: no app login; everyone using the instance sees the
  same Graph mailbox.
- `--provider powerautomate`: login page at `/login`. Each account in
  `private/multiuser.json` sees only its own pushed mail.
- Students can create their own account at `/register` (link on the sign-in page). Each gets a fresh webhook token, shown in the in-app Connect Outlook guide. Accounts you add by hand in `private/multiuser.json` still need a restart.
- Sign-ins are kept in a session cookie for 12 hours; use **Sign out** in the
  top-right chip to end early. The session-signing key is stored in
  `private/session_secret` (or the `SESSION_SECRET` env var), so people stay
  signed in across app restarts.

---

## Classifier backends

The default is `hybrid_claude`:

| Backend | Category | Action | Requirements |
|---|---|---|---|
| `hybrid_claude` (default) | ML `LinearSVC` | Claude | ML category model + `ANTHROPIC_API_KEY` in `claude/.env` |
| `hybrid` | ML `LinearSVC` | text encoder `e5-small-multi` | ML category model + `text-encoders/models/action_head/` |
| `encoder` | `bge-small-en` head | `e5-small-multi` head | `text-encoders/models/{category,action}_head/` |
| `ml` | ML `LinearSVC` | ML `BalancedComplementNB` | both `classical-ml/artifacts/*.joblib` |
| `llama` | Llama 3.1 8B | Llama 3.1 8B | `ollama pull llama3.1:8b`, Ollama running |
| `claude` | Claude | Claude | `ANTHROPIC_API_KEY` in `claude/.env` |

```bash
python email-sorter/run.py --port 5001                      # hybrid_claude
python email-sorter/run.py --port 5001 --backend encoder
python email-sorter/run.py --port 5001 --backend llama
python email-sorter/run.py --port 5001 --backend ml
```

`--backend` overrides `MODEL_BACKEND`. The dashboard shows whether the selected
backend is ready.

Train missing models:

```bash
# text encoders
python text-encoders/train.py --task category
python text-encoders/train.py --task action --synthetic data/synthetic.csv

# classical ML
cd classical-ml
PYTHONPATH=src python -m train_email_ml
```

The Claude backend loads `claude/` under an alias and keeps its pipeline:
sender rules → Claude API → guardrails → fallback. It needs the key in
`claude/.env`.

Sender category rules in `app/classifiers/sender_rules.py` apply to every backend. A matching rule
overrides only the category; the backend still classifies action, deadline, and
reason.

---

## Dashboard

- **Today:** what is due, upcoming events, and the emails that need action,
  ordered by priority. Each email shows why it got its priority, and the
  student can change it.
- **Inbox:** every loaded email with its category, action and priority, plus
  filters, a time window and search. A wrong label can be corrected.
- **Calendar:** deadlines and events found in emails, the NUS academic
  calendar, and the student's own events. It can be subscribed to or exported
  as an `.ics` feed.
- **Courses and jobs:** mail grouped by course code, and job posts that can be
  saved.
- **Replies:** for emails that need a reply, Claude drafts one. It is sent only
  when the student presses send.

Dates use Singapore time. The app never changes the student's mailbox or
Outlook calendar.

Inline-image OCR is optional. Install Tesseract:

```bash
brew install tesseract        # macOS
```

Set `OCR_ENGINE=off` to disable it, `OCR_LANG=eng` for the language, or
`TESSERACT_CMD=/path/to/tesseract` if it is not on `PATH`. Only inline images
are read; ordinary attachments and linked images are ignored.

---

## API

| Route | Purpose |
|---|---|
| `GET /` | React dashboard (`static/app/`) |
| `GET /api/backends` | Backends, labels, readiness |
| `GET /api/taxonomy` | Category/action labels |
| `GET /api/health?backend=` | Readiness for one backend |
| `POST /api/emails` | Fetch mail. Body: `provider`, `credentials`, optional `since`/`before`, `count` |
| `POST /api/classify` | Classify one email with an optional `backend` |
| `POST /api/inbound/outlook` | Power Automate push (webhook token, no login needed) |
| `GET /api/inbound/diagnostics` | This account's recent push attempts (signed-in session) |
| `POST /api/inbound/refresh` | Trigger this account's flow (signed-in session) |
| `GET/POST /api/events`, `/api/item-states`, `/api/saved-jobs` | Personal events, done/snoozed items, saved jobs |
| `GET /api/feed`, `GET /feed/<name>` | Calendar feed settings and the `.ics` subscription |
| `POST /api/draft-reply`, `POST /api/send-reply` | Draft a reply with Claude; send it on the student's request |

---

## Key files

| Path | Purpose |
|---|---|
| `app/server.py` | App factory: sign-in, CSRF and security headers, dashboard and error pages |
| `app/routes/` | HTTP routes, one blueprint per area (account, inbound, mail, corrections, replies, planner) |
| `app/classifiers/` | Backend registry (`backends.py`), the ML, Claude, encoder, Llama and hybrid backends, sender rules, timing logs |
| `app/extract/` | Deadlines and the NUS academic calendar, poster OCR and QR codes, job listings |
| `app/mail/` | Mail providers (Graph, pushed), pushed-mail store, Power Automate flow package, reply drafting and sending |
| `app/stores/` | Per-user data under `private/`: corrections and cache, profiles, item states, events, feed, saved jobs |
| `app/accounts.py` | Login page, sessions, and account lookup |
| `app/config.py`, `app/schemas.py`, `app/taxonomy.py` | Settings, data shapes, and the category/action labels |
| `app/ngrok.py` | Automatic ngrok tunnel |
| `frontend/` | React + TypeScript dashboard, built into `static/app/` (see [`frontend/README.md`](frontend/README.md)) |
| `templates/` | Sign-in, sign-up and Connect Outlook pages, error page |
| `static/` | CSS and logo for those pages; `static/app/` is the built dashboard (gitignored) |
| `static/vendor/tabler/` | Locally hosted Tabler CSS + license (no build step) |

### UI kit and licenses

The sign-in pages use selected components from the open-source **Tabler** UI
kit (vendored, version-pinned, no remote scripts).

- Tabler CSS: **v1.7.3** (`@tabler/core`), MIT — hosted at
  `static/vendor/tabler/tabler.min.css`. Attribution and integrity hash in
  `static/vendor/tabler/NOTICE.txt`; full MIT text in `.../LICENSE`.
- It bundles Bootstrap 5 CSS (MIT, The Bootstrap Authors), redistributed by
  Tabler. No separate Bootstrap or Tabler **JavaScript** is used.
- Icons are a small set of **Tabler Icons v3.50.0** (MIT) inlined as plain SVG
  (`templates/_icons.html`); no icon webfont is loaded.
- `static/style.css` loads **after** `tabler.min.css` and stays the override
  layer; it maps the adopted pieces to this app's palette and system font
  stack.
- No external fonts, analytics, or remote scripts are added.

## Tests

```bash
cd email-sorter
pytest -q
```
