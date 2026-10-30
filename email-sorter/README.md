# Email sorter app

A Flask dashboard that loads recent email, classifies each message into one
**category** and one **action**, and shows the result in a table and calendar.

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
| `MAIL_PROVIDER` | `graphtoken` | `graphtoken` or `powerautomate` |
| `MODEL_BACKEND` | `hybrid_claude` | default classifier backend |
| `PORT` | `5000` | use `5001` if 5000 is taken |
| `MAX_EMAILS` | `100` | load cap per batch |
| `INBOUND_MAX_EMAILS` | `500` | pushed-mail memory cap |

Run from the repo root:

```bash
python email-sorter/run.py
# open http://127.0.0.1:5000
```

If port 5000 is busy (macOS Control Center uses it):

```bash
python email-sorter/run.py --port 5001
```

Dashboard v2 is the default home page. The older page is still available:

```bash
python email-sorter/run.py -version 1
```

---

## Mail sources

The source is fixed at launch with `--provider`; the browser does not ask for a
source.

### Graph token (default)

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

- Adds a per-user app login (HTTP Basic auth).
- Starts ngrok automatically for the app port using
  `chive-suitably-slingshot.ngrok-free.dev`.
- Use `--no-tunnel` to skip ngrok, or
  `--ngrok-domain other.ngrok-free.dev` for another reserved domain.

The first time, create the private account file:

```bash
cd email-sorter
python tools/configure_multiuser.py
```

It asks for:

- the account email,
- an app-only password (16+ characters),
- an optional Power Automate trigger URL.

It writes `private/multiuser.json` with `600` permissions and prints the
account's **webhook token**. To print a token again:

```bash
cd email-sorter
python - <<'PY'
import json, pathlib
accounts = json.loads(pathlib.Path("private/multiuser.json").read_text())
print(accounts["you@u.nus.edu"]["webhook_token"])
PY
```

#### Power Automate flow

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
the dashboard. Put its URL in the account's `refresh_url` field (rerun
`tools/configure_multiuser.py` or edit `private/multiuser.json`) and restart the
app. The trigger body may include:

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

- Pushed mail lives in memory (newest 500 by default) and is cleared on restart.
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
- `--provider powerautomate`: HTTP Basic auth. Each account in
  `private/multiuser.json` sees only its own pushed mail.
- Accounts are loaded at startup; restart after adding a user.
- The browser may cache Basic-auth credentials. The app changes the realm on
  each start so the login popup appears again.

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

Sender category rules in `app/sender_rules.py` apply to every backend. A matching rule
overrides only the category; the backend still classifies action, deadline, and
reason.

---

## Dashboard workflow

1. Load the newest messages up to **Max emails**.
2. Choose a **Time window**; this filters the loaded messages locally.
3. Press **Start classification** to classify only the visible window.

The same loaded set feeds the **Calendar** tab:

- Canvas assignment notifications are parsed for explicit deadlines.
- The NUS academic calendar is shown as separate context labels.
- Dates use Singapore time and English formatting.
- The app never writes to your calendar or mailbox.

Inline-image OCR is optional. Install Tesseract:

```bash
brew install tesseract        # macOS
```

Set `OCR_ENGINE=off` to disable it, `OCR_LANG=eng` for the language, or
`TESSERACT_CMD=/path/to/tesseract` if it is not on `PATH`. Only inline images
are read; ordinary attachments and linked images are ignored.

---

## Compare backends from the CLI

The browser comparison page is gone. Start the app, then run the CLI in a
second terminal. The CLI fetches through the running app's `/api/emails`,
classifies locally, and prints latency and agreement. It does not start a second
Flask server.

```bash
# all backends, last 7 days (app running on port 5001)
python email-sorter/run.py --compare --port 5001 \
  --provider graphtoken --token "$GRAPH_TOKEN"

# choose backends and save a CSV
python email-sorter/run.py --compare --port 5001 \
  --provider graphtoken --token "$GRAPH_TOKEN" \
  --backends llama,ml --days 30 --output compare.csv
```

Pushed-mail instances require the app login, so the CLI comparison currently
targets a Graph-token instance.

---

## API

| Route | Purpose |
|---|---|
| `GET /` | Dashboard v2 (default) |
| `GET /dashboard-v2` | Dashboard v2 |
| `GET /api/backends` | Backends, labels, readiness |
| `GET /api/taxonomy` | Category/action labels |
| `GET /api/health?backend=` | Readiness for one backend |
| `POST /api/emails` | Fetch mail. Body: `provider`, `credentials`, optional `since`/`before`, `count` |
| `POST /api/classify` | Classify one email with an optional `backend` |
| `POST /api/inbound/outlook` | Power Automate push (webhook token, no Basic auth) |
| `GET /api/inbound/diagnostics` | This account's recent push attempts (Basic auth) |
| `POST /api/inbound/refresh` | Trigger this account's flow (Basic auth) |

---

## Key files

| File | Purpose |
|---|---|
| `app/server.py` | Flask routes, auth, health |
| `app/backends.py` | Backend registry and factory |
| `app/schemas.py` | Email and classification schemas |
| `app/encoder_classifier.py` | Text-encoder heads |
| `app/ml_classifier.py` | Classical ML pipelines |
| `app/llama_classifier.py` | Ollama backend |
| `app/claude_classifier.py` | Claude backend |
| `app/hybrid_classifier.py` | ML + encoder/Claude hybrids |
| `app/accounts.py` | Basic auth and account lookup |
| `app/pushed_store.py` | Per-user pushed-mail store |
| `app/sender_rules.py` | Sender-based category overrides |
| `app/calendar.py` | Deadline extraction and the NUS academic calendar |
| `app/ocr.py` | Inline-image OCR |
| `app/ngrok.py` | Automatic ngrok tunnel |
| `app/providers/` | Graph and pushed-mail sources |
| `templates/` | Dashboard pages |
| `static/` | JavaScript and CSS |

## Tests

```bash
cd email-sorter
pytest -q
```
