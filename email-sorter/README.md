# Inbox sorter

Fetches recent emails and classifies their content and reply/action type. Mail
comes from either a Power Automate flow that pushes each message to the app, or
the Outlook Graph API with a token pasted into the dashboard toolbar. Pick one
at launch with `--provider`; the dashboard never stores a mailbox password.

| Page | Purpose |
|------|---------|
| `/` | Sorter or triage dashboard, selected at launch. |
| `/dashboard-v2` | Inbox dashboard with the calendar view. |

Backend comparison lives in the terminal now; see
[Compare backends from the CLI](#compare-backends-from-the-cli).

## Setup
```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
python run.py
```

Open <http://127.0.0.1:5000>. Choose the home dashboard with:

```bash
python run.py             # dashboard v2 (default)
python run.py -version 1  # original sorter
```

`--version` is also accepted. Version 2 is the default home page and is also
available at `/dashboard-v2`.

## Choosing the mail source

The source is fixed when the app starts, not in the browser:

```bash
python run.py --version 2 --provider graphtoken      # default: paste a Graph token
python run.py --version 2 --provider powerautomate   # the flow pushes mail
```

`MAIL_PROVIDER=graphtoken` is the default in `.env`; set
`MAIL_PROVIDER=powerautomate` or pass `--provider powerautomate` to switch. A
Graph token is entered in the dashboard popup each time (or refreshed when it
expires); the Power Automate source needs no token because the flow
authenticates on its own.

## OCR for inline images

The fetch step runs local Tesseract OCR on inline image attachments when an
email body has fewer than 100 characters. Install Tesseract separately:

```bash
brew install tesseract          # macOS
```

On other platforms, install Tesseract and make its executable available on
`PATH`. Pillow is installed with the Python requirements. Optional `.env`
settings are `OCR_ENGINE=off` to disable OCR, `OCR_LANG=eng` to choose the
Tesseract language, and `TESSERACT_CMD=/path/to/tesseract` when it is not on
`PATH`.

Only inline image attachments are read. Ordinary file attachments and images
that are only linked from an external website are not fetched. The UI shows
the OCR text source, confidence, and any warnings. OCR output can be inaccurate,
so verify extracted text before relying on its classification.

## Load, choose a window, then classify

Dashboard v2 keeps the three steps separate:

1. On launch the email gate opens, prefilled with the address remembered in this
   browser. Mail is loaded only after you press **Continue**.
2. The dashboard loads the newest messages up to `Max emails` (default 100) and
   shows them as **Not classified**. Nothing is sent to a model yet.
3. Choosing a **Time window** filters the messages already loaded in the
   browser. It does not fetch the mailbox again.
4. Press **Start classification** to classify only the messages in the current
   window.

`Max emails` is the load cap (also `MAX_EMAILS` in `.env`, default 100). If the
mailbox has more messages than the cap, the newest ones win. The window options
are:

| Option | Effect |
|--------|--------|
| Last 24 hours / 7 / 30 / 90 days | Rolling window ending now |
| Custom range | Explicit **From** and **To** dates |

The same loaded set drives the calendar's **Upcoming deadlines** list and month
view, so Canvas assignments follow the selected window. For a semester-wide
deadline sweep choose **Last 90 days** or a custom range. The NUS academic
calendar is separate: it always shows the official term dates and does not
depend on which mail is loaded.

## Rule-based deadline calendar

Dashboard v2 checks email subject/body text for explicit deadline or exam
phrases such as `due: 13 Nov at 23:59`, `deadline: 13 November 2026`,
`submit by Nov 13`, or `Final exam will be held on 20 Nov 2026 at 9:00 am`.
This date extraction uses regular expressions and Python's standard library,
not a model. Dates without a year use the email's received date to infer one
and are marked for review. Unsupported or ambiguous wording is left unmatched.

Only Canvas assignment notifications appear in the calendar. Canvas
announcements, quizzes/exams, and ordinary mail are ignored even when they
contain a date. Open the **Calendar** tab to see those assignments as a list
grouped by day (today and tomorrow are labelled), with the month view on the
left and the list on the right. Each row shows the course code as a colored
token, the assignment title, and the due time. Click a row to open the email and
verify the detected text. In the month view, each day shows its items as
colored title-only chips; selecting a day scrolls the list to that date. The
token strip above the calendar lists every course found in Canvas mail,
including courses that only sent announcements and have no assignment deadline.

Calendar titles remove Canvas prefixes such as `Assignment created -` and show
the actual title and time. Course codes found in the subject or message (for
example `DSS5202`) get a consistent color and appear as a token on every event.
Events without a recognizable course code use a neutral color. Canvas
notifications use their footer link (`View assignment` or `View announcement`)
before any keyword guessing, so an announcement is never added as an
assignment. Only messages
that are both from Canvas and classified as an assignment reach the calendar.
Choose **Scan mailbox** to fetch and extract without calling a
classifier. Dates and times are always shown in English using Singapore time,
regardless of the browser's locale. The app does not write to your calendar or
mailbox. For times without a specified timezone, the event uses Singapore time.
This initial version does not export `.ics` files, parse `.ics` attachments, or
handle dates phrased only as weekdays.

### NUS academic calendar context

The calendar also reads `data/nus_academic_calendar_AY2026_2027.csv`, served by
`GET /api/academic-calendar`. Orientation, semester and special-term ranges,
reading and exam weeks, public holidays, and vacations appear as small labels at
the bottom of the month-grid day cell, separate from the Canvas assignment
chips. Rows with `mark=1` span a range: the event appears on both its start and
end date (`↦` marks the start, `↤` marks the end); other rows show their single
date. The **Academic calendar** panel beside the deadlines lists the events that
overlap the month you are viewing, with their date range and any notes. These are
context only: they are not Canvas assignments and do not change the assignment
count on the Calendar tab. Update the CSV to
refresh the dates; no code change is needed.

## Push mail from Power Automate

The app can also receive mail that a Power Automate flow pushes to it, which
avoids pasting a Graph token into the dashboard. This uses HTTPS, not a
WebSocket: the flow collects Outlook mail and an HTTP action posts each message
to the app.

In `powerautomate` mode, `run.py` starts ngrok automatically for the app port
using the static domain in `NGROK_DOMAIN` (default:
`chive-suitably-slingshot.ngrok-free.dev`). Use `--no-tunnel` to skip it, or
`--ngrok-domain other.ngrok-free.dev` to use another reserved domain.

1. Create the account (or reuse an existing one) and get its webhook token. In
   the multi-user app, each push is authenticated with the account's
   `webhook_token` from `private/multiuser.json` — not the
   `POWER_AUTOMATE_WEBHOOK_TOKEN` in `.env`.

   ```bash
   cd email-sorter
   python tools/configure_multiuser.py   # first time only
   # print the token you already created
   python -c "import json,pathlib; print(next(iter(json.loads(pathlib.Path('private/multiuser.json').read_text()).values()))['webhook_token'])"
   ```

   Keep `INBOUND_MAX_EMAILS=500` in `.env` if you want a larger in-memory store.
   The account's `refresh_url` (asked for by the script) is what the dashboard's
   refresh button calls; `.env`'s `POWER_AUTOMATE_REFRESH_URL` is not used on
   this branch.

2. In Power Automate, build a flow that collects a window of mail and posts each
   message to the app (an HTTP action requires a premium connector):

   ```
   Recurrence (or When an HTTP request is received)
    └─ Get emails (V3)      Folder=Inbox, Top=200, Unread=No
        └─ Apply to each    input: value
            └─ HTTP         POST https://your-ngrok-domain/api/inbound/outlook
   ```

   Use `received>=` plus a date in the **Search query** to bound the window:
   `concat('received>=', formatDateTime(addDays(utcNow(), -30), 'yyyy-MM-dd'))`.

   HTTP action settings:

   - Method: `POST`
   - URI: `https://your-ngrok-domain/api/inbound/outlook`
   - Header: `Content-Type: application/json`
   - Header: `X-Webhook-Token: <the token printed in step 1>`
   - Header: `X-User-Email: <the mailbox this flow watches>`
   - Header: `ngrok-skip-browser-warning: true` (only needed for free ngrok tunnels)
   - Body (inside the loop, so `item()` refers to the current message):

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

   `Get emails (V3)` returns `from` and `body` as plain strings, unlike the
   "new email arrives" trigger, so do not select `?['emailAddress']` or
   `?['content']` here. The app also accepts the nested Graph shape.

3. Open the dashboard: with `--provider powerautomate` (the default) there is no
   source dropdown or credential to fill in. Pushed messages work like fetched
   ones, including classification, deadline extraction, and the calendar. The
   dashboard checks the queue every 20 seconds, so new pushes appear without
   pressing anything again.

If the flow omits `X-User-Email`, the app falls back to the first To recipient
of the message, which is normally the mailbox the flow watches.

### Triggering a backfill from the dashboard

A flow that starts with **When an HTTP request is received** can be started by
the dashboard instead of a schedule. In the trigger's request body schema, use:

```json
{
  "type": "object",
  "properties": {
    "owner": { "type": "string" },
    "since": { "type": "string" },
    "before": { "type": "string" }
  }
}
```

Use `triggerBody()?['since']` in the search query. Keep `X-User-Email` set to
the mailbox this flow watches, not the viewer's address: one flow reads one
mailbox, so tagging its mail with whoever happened to open the dashboard would
show that mailbox to the wrong person. Then copy the trigger URL into `.env` as
`POWER_AUTOMATE_REFRESH_URL` and restart the app. After that:

- entering an email at the gate asks the flow for the latest mail once,
- changing **Time window** only filters mail that is already loaded and does not
  start the flow,
- every message the flow pushes arrives through the normal webhook.

The dashboard toolbar shows the trigger result under the webhook status line. If the app
reports that the URL expired, copy the trigger URL again from the flow.

### The flow does not start when I open the dashboard

Only a flow that starts with **When an HTTP request is received** can be started
by the app; a **Recurrence** (scheduled) trigger has no URL to call. If you want
both behaviours, duplicate the flow: keep the scheduled copy as it is, give the
other copy the HTTP trigger, and point `POWER_AUTOMATE_REFRESH_URL` at that
copy. Duplicate pushes are ignored per person.

Notes:

- Pushed mail is kept in memory (newest 500 by default) and is cleared when the
  app restarts.
- Duplicate message ids are ignored per person, so Power Automate retries are
  safe without hiding a shared message from someone else.
- HTML bodies are converted to text. Attachments are not processed by this
  path; inline-image OCR needs the Outlook Graph source.
- Keep the ngrok tunnel private or stop it when you are done. The webhook
  rejects requests that do not include the shared token.
- Quitting the app does not stop the flow: a scheduled or trigger-based flow
  runs in Power Automate's cloud. Turn the flow off (or disable its HTTP action)
  in Power Automate when you are done. Pushes sent while the app is stopped are
  simply rejected and are not stored.
- Opening `https://…/api/inbound/outlook` in a browser shows a **405 Method Not
  Allowed** page. That is expected: the endpoint only answers `POST`, so the
  HTTP action's Method must be `POST`, not the default `GET`.
- A flow that posts to the tunnel root (`/`) instead of the full path still
  delivers its mail: any `POST` to `/` or `/dashboard-v2` carrying a valid
  `X-Webhook-Token` is accepted, the response adds a `warning`, and the
  dashboard asks you to append `/api/inbound/outlook` to the URI.

## Several people, one app

One running app can serve several students. Every launch opens a gate that asks
for (or confirms) an email address and stores it in `localStorage`; mail is
loaded only after you press **Continue**. The address is shown top right, and
clicking it switches user (dashboard v2 clears the previous person's mail and
loads the new person's mail, so one inbox is never left on screen for the next
person).

Every request from the browser carries `X-User-Email`, and pushed mail is filed
under the owner that sent it, so each person only sees their own messages.
Messages with no owner are only visible to requests without an identity, which
is why the Power Automate flow should send the header above.

With `--provider graphtoken` there is only one token, so everyone using that
running app sees the same Graph mailbox; per-user separation applies to pushed
mail. Run a separate instance on another port if two people need different
Graph mailboxes.

This is identification, not authentication: anyone who can open the app can type
any address. A shared passcode can be added later by validating the same header
in one place (`_request_user` in `app/server.py`).

## Compare backends from the CLI

The comparison screen is gone from the browser. Start the app as usual, then
run the CLI in a second terminal:

```bash
# All registered backends, last 7 days, your pushed inbox
python run.py --compare --owner you@u.nus.edu

# Pick backends, widen the window, and save a CSV
python run.py --compare --owner you@u.nus.edu --backends llama,ml --days 30 \
  --output reports/compare.csv

# A Graph-token instance instead of pushed mail
python run.py --compare --provider graphtoken --token "$GRAPH_TOKEN"
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--backends` | `all` | Comma-separated backend names (`hybrid_claude`, `hybrid`, `llama`, `bert`, `ml`, `claude`). |
| `--days` | `7` | Received-date window; `0` disables it. |
| `--limit` | `MAX_EMAILS` | Maximum emails to classify. |
| `--owner` | `MAIL_OWNER` | Mailbox address, so the CLI sees the same pushed inbox as the dashboard. |
| `--url` | `http://127.0.0.1:PORT` | Running app to fetch the batch from. |
| `--output` | none | Write per-email results to a CSV file. |
| `--token` | `GRAPH_TOKEN` | Outlook Graph token for `--provider graphtoken`. |

The CLI fetches through the running app's `/api/emails`, because pushed mail
lives in the app's memory. It then classifies locally with each backend and
prints latency, label agreement, and per-email results. The app does not need
to be restarted, and the CLI exits without starting a second Flask server.

## Choosing a backend

Pick **Hybrid (ML + Claude)**, **Hybrid (ML + BERT)**, **Llama**, **Text
encoders**, or **Classical ML** in the dashboard toolbar (or the sidebar on the
original sorter page). The choice is saved in your browser and does not require
a server restart.

`MODEL_BACKEND` in `.env` or `--backend` sets the initial default for browsers
without a saved choice. The default is `hybrid_claude`: the content category
comes from the classical TF-IDF model and the reply nature comes from Claude,
so each task uses its stronger pipeline.

```bash
python run.py                         # hybrid_claude (default)
python run.py --backend hybrid        # ML category + BERT action
python run.py --backend bert          # both tasks from the BERT heads
MODEL_BACKEND=ml python run.py        # both tasks from the TF-IDF pipelines
```

Only the halves a backend needs are loaded. `hybrid_claude` loads
`classical-ml/artifacts/email_category_model.joblib` for the category and the
Claude pipeline for the action; `hybrid` loads the same category model plus
`text-encoders/models/action_head/` for the action.

The classical ML models are not committed. Generate them before using
`hybrid_claude`, `hybrid`, or `ml`:

```bash
PYTHONPATH=../classical-ml/src .venv/bin/python -m train_email_ml
```

The encoder backend still uses the `bert` key in configuration and CLI options
for compatibility with existing scripts.

Sender category rules in `app/rules.py` are applied to results from every
backend. A matching rule overrides only the content category; the selected
backend still classifies reply nature, deadline, and reason.

| Backend | Description | Requirements |
|---------|-------------|--------------|
| `hybrid_claude` | ML category (`LinearSVC`) + Claude action — default | ML category model and `ANTHROPIC_API_KEY` in `inbox-sorter/.env` |
| `hybrid` | ML category (`LinearSVC`) + BERT action head (`e5-small-multi`) | ML category model and `text-encoders/models/action_head/` |
| `llama` | Llama via Ollama | `ollama pull llama3.1:8b`, Ollama running |
| `bert` | Frozen text encoders + logistic heads (tiny, fast) | `text-encoders/models/{category,action}_head/` trained via `text-encoders/train.py` |
| `ml` | Classical TF-IDF pipelines | Production model files generated by `train_email_ml` |
| `claude` | Anthropic Claude through the inbox-sorter pipeline | `ANTHROPIC_API_KEY` in `inbox-sorter/.env`; `anthropic` installed |

The Claude backend loads `inbox-sorter/` under an alias and keeps its pipeline
intact (sender rules → Claude API → guardrails → fallback). It needs the
Anthropic key in `inbox-sorter/.env` and does not use the local models.

Backends are registered in `app/classifier_base.py`. To add one:

1. Implement `BaseClassifier` (see `app/llama_classifier.py` or `app/bert_classifier.py`).
2. Add metadata to `BACKEND_INFO` in `app/classifier_base.py`.
3. Add a branch in `create_classifier()`.

## Train BERT models

From the project root:

```bash
.venv/bin/python text-encoders/train.py --task category
.venv/bin/python text-encoders/train.py --task action --synthetic data/synthetic.csv
```

Models are written to `text-encoders/models/{task}_{head,full}/`. The app uses the `_head`
variants by default. Large `model.safetensors` files are ignored by Git.

## API

| Route | Purpose |
|-------|---------|
| `GET /` | Selected dashboard |
| `GET /dashboard-v2` | Dashboard v2 |
| `GET /api/backends` | Registered backends, labels, readiness |
| `GET /api/taxonomy` | Category/action labels and max email count |
| `GET /api/health?backend=` | Readiness for one backend |
| `POST /api/emails` | Fetch emails in a time window. Body: `provider`, `credentials`, optional `since`/`before` (ISO 8601, inclusive), `count` (cap). Returns `emails` + `window`. |
| `POST /api/classify` | Classify one email (optional `backend`) |

## Key files
- Categories and wording: `app/taxonomy.py`
- Prompt and model call (Llama): `app/llama_classifier.py`
- Text-encoder wrapper: `app/bert_classifier.py`
- Backend registry and factory: `app/classifier_base.py`
- Shared frontend helpers: `static/common.js`
- Sorter page: `templates/index.html`, `static/sorter.js`
- Dashboard v2: `templates/dashboard_v2.html`, `static/dashboard_v2.js`
- Backend comparison CLI: `app/compare_cli.py`, flags in `run.py`
- Shared styles: `static/style.css`
- New mail source: add a file in `app/providers/` and one line in `app/providers/__init__.py`
