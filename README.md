# NusBox — DSS5105 Track 4, Group 13

NusBox is an email assistant for NUS students. It reads a student's Outlook
mail, sorts each message into a **category** and an **action**, scores its
priority, and pulls out deadlines, events and job posts into a Today page and a
calendar.

The repository also holds the model work behind it: four ways to classify the
same emails, and one evaluation that compares them (see
[The four methods](#the-four-methods)). The app ships with `hybrid_claude`: the
classical-ML model picks the category and Claude picks the action.

---

## Features

- **Today page:** what is due, upcoming events, and the emails that need
  something. Items can be marked done or snoozed.
- **Priority stars with reasons:** each email gets 1 to 5 stars, the inbox can
  be sorted by them, "Why?" shows what they came from, and the student can set
  them by hand.
- **Corrections that stick:** fixing a label can also create a rule for that
  sender, so their next emails are sorted the same way without a model call.
- **Dates from mail:** deadlines, exams and events go to the calendar, which
  other calendar apps can subscribe to (`.ics`) or import.
- **Posters:** text and QR codes are read from image-only emails.
- **Job digests:** a careers newsletter becomes a list of jobs that can be
  saved.
- **Course pages:** mail grouped by course code, with Canvas notifications.
- **Reply drafts:** Claude drafts a reply to emails that need one, marks the
  blanks the student must fill in, and sends only when the student presses
  Send.
- **Incremental sync:** after one complete Power Automate refresh, later
  refreshes only fetch newer mail.

## How it works

```
Outlook mailbox
  ├─ pasted Microsoft Graph token ──── the app reads the mail itself
  └─ the student's Power Automate flow ── pushes each email to /api/inbound/outlook
                     │
                     ▼
Flask backend (email-sorter/app)
  1. date, event, job and poster extraction (no model needed)
  2. sender and course rules       (free shortcuts, e.g. Canvas notifications)
  3. classifier backend            (hybrid_claude: ML category + Claude action, stars, date)
  4. the student's own corrections and sender rules always win; results are cached
                     │
                     ▼
React dashboard (email-sorter/frontend)
  Today · Inbox · Calendar (+ .ics feed) · course pages · job posts · reply drafts
```

## Labels

Every email gets one category and one action.

| Category | Meaning |
|---|---|
| Medical | Health, clinic or hospital messages, appointments, insurance, vaccination, counselling, medical certificates |
| Promotional | Marketing, offers, discounts, newsletters, sales, advertising of events or products |
| Career related | Jobs, internships, recruiters, career fairs, CV or interview help, networking |
| Canvas | Automated notifications from the Canvas learning platform: announcements, assignment due dates, grades, discussion posts |
| General | Everyday university or personal messages: announcements, timetables, campus notices, lecturers, classmates |
| Others | Anything that clearly fits none of the above |

| Action | Meaning |
|---|---|
| Needs action | The reader must do something other than write back: fill a form, submit, register, pay, sign, upload |
| Needs a reply | A person is asking a question or expecting a written response |
| Reminder | Contains a date or time limit but asks for no specific action or reply |
| Further review | Informational, automated or promotional; nothing needs to be done now |

The labels and their descriptions live in `email-sorter/app/taxonomy.py`
(and `claude/config.yaml` for the Claude prompt).

## Priority stars

In the same call that picks the action, Claude scores three things about the
email's content, each from 0 to 3:

- **consequence:** what happens if it is ignored,
- **urgency:** how soon it matters. When the email gives a deadline, urgency
  is counted from the day it arrived: overdue or within 2 days = 3, within a
  week = 2, within 30 days = 1, later = 0,
- **relevance:** from mass marketing (0) to something addressed to the student
  personally (3).

A fixed formula turns them into stars, so the same scores always give the
same stars:

```
score = 2.0 × consequence + 1.5 × urgency + 1.0 × relevance      (0 to 13.5)
stars: 5 ≥ 11.5 · 4 ≥ 9 · 3 ≥ 6 · 2 ≥ 3 · otherwise 1
```

Then three guardrails apply: a serious email due within a week gets at least
4 stars, mass marketing at most 3, and a likely phishing email at most 2 (with
a warning). The category and action labels play no part in the stars. The
weights and limits are in `claude/config.yaml` (`priority`); the code is
`claude/src/priority.py`.

## Privacy and data

- **Sent to Claude:** with the `hybrid_claude` or `claude` backend, the
  email's subject and text are sent to Anthropic to sort it or draft a reply.
  The other backends send nothing out.
- **Saved only on this computer:** accounts, mail and results are kept in
  `email-sorter/private/`, which is never committed.
- **Outlook tokens are never saved** to disk.
- **The mailbox is only read.** The app sends a reply only when the student
  presses Send.
- **Local by default:** only `--tunnel` makes the app reachable from outside,
  and it still needs a sign-in.

---

## Quick start

Needs **Python 3.10+** (CI uses 3.12) and **Node 22** with `npm`. Use one
virtual environment at the repo root.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
make install                       # Python packages + frontend packages

cp email-sorter/.env.example email-sorter/.env
python email-sorter/run.py
# open http://127.0.0.1:5001
```

Without `make` (usual on Windows), run what `make install` does, and copy the
`.env` file with `copy` instead of `cp`:

```bash
pip install -r requirements.txt
cd email-sorter/frontend && npm ci && cd ../..
```

`run.py` rebuilds the React frontend when its code has changed, so it needs
`npm` and the install above done once.

**Optional: Tesseract** reads the text on poster images. Without it the app
still runs, and image-only emails are sorted from their sender and subject.

```bash
brew install tesseract              # macOS
sudo apt install tesseract-ocr      # Ubuntu / Debian
# Windows: install from https://github.com/UB-Mannheim/tesseract/wiki
```

If it is installed somewhere unusual, set `TESSERACT_CMD` in
`email-sorter/.env` to its path. The dashboard sidebar shows whether image
reading is ready.

To run only the app (no model training or evaluation), install the much
lighter `requirements-app.txt` instead of `requirements.txt`:

```bash
pip install -r requirements-app.txt
(cd email-sorter/frontend && npm ci)
```

### Trying it from a fresh clone

The default backend needs an Anthropic API key and the classical-ML model,
and neither is in the repository (the model is trained on private student
mail). Without them:

| You have | Start with | What works |
|---|---|---|
| Nothing | `python email-sorter/run.py` | Everything except sorting: deadlines, calendar, course pages, job posts |
| `ANTHROPIC_API_KEY` in `claude/.env` | `--backend claude` | Everything, with Claude alone |
| Full `requirements.txt` | `--backend encoder` | Free sorting with the committed encoder heads (downloads BGE/E5 on first run) |

To sign in with your own Outlook mail:

1. Open [Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer)
   and sign in with your Outlook (NUS) account.
2. Under **Modify permissions**, consent to `Mail.Read` (and `Mail.Send` to
   send replies).
3. Open the **Access token** tab and copy the token.
4. On the app's sign-in page, choose "Use an Outlook token instead" and paste
   it.

The token expires after about an hour; paste a fresh one when asked. Only NUS
addresses are accepted unless `ALLOWED_EMAIL_DOMAINS` is set in
`email-sorter/.env`.

### Defaults

- **Port:** `5001` (macOS AirPlay Receiver uses 5000).
- **Mail source:** `powerautomate`. Students sign up or sign in, then connect
  Outlook with their own Power Automate flow or a pasted Microsoft Graph token.
- **Backend:** `hybrid_claude`.
- **ngrok:** off. The live machine shares the app with `--tunnel`.

For a quick local test without accounts, paste a Graph token instead:

```bash
python email-sorter/run.py --provider graphtoken
```

### Backend requirements

| Backend | Needs |
|---|---|
| `hybrid_claude` (default) | `classical-ml/artifacts/email_category_model.joblib` + `ANTHROPIC_API_KEY` in `claude/.env` |
| `hybrid` | ML category model + `text-encoders/models/action_head/` |
| `encoder` | `text-encoders/models/{category,action}_head/` |
| `ml` | both classical-ML artifacts |
| `llama` | `ollama pull llama3.1:8b` and Ollama running |
| `claude` | `ANTHROPIC_API_KEY` in `claude/.env` |

The dashboard shows which backend is ready. To train the classical-ML models
yourself you need the private `data/labels.csv` (see
[`classical-ml/README.md`](classical-ml/README.md)).

---

## The four methods

Each task goes to the method that did best on it in the evaluations (accuracy
on the labelled student emails):

| Method | Folder | Category | Action |
|---|---|---:|---:|
| Classical ML: TF-IDF + LinearSVC / ComplementNB | `classical-ml/` | **0.886** | 0.806 |
| Text encoders: frozen BGE / E5 heads, plus DistilBERT fine-tunes | `text-encoders/` | 0.864 | 0.843 |
| Llama 3.1 8B through Ollama (built into the app) | `email-sorter/` | 0.720 | 0.776 |
| Claude with sender rules and guardrails | `claude/` | 0.833 | **0.888** |

That is why the default is `hybrid_claude`: classical ML for the category and
Claude for the action. The category model is also free and runs in under a
millisecond, so only the action (and the stars and date, from the same call)
needs Claude. The first three rows are the committed out-of-fold run (n=132
category, n=134 action); the Claude row is from a separate run on the Claude
integration branch, and the `hybrid_claude` combination has not been scored as
one system. Details and caveats are in
[`docs/MODEL_COMPARISON.md`](docs/MODEL_COMPARISON.md) (section 8).

## Training the methods

Both trained methods need the private `data/labels.csv`.

```bash
# Text encoders: category and action heads (synthetic rows go to action only)
python text-encoders/train.py --synthetic data/synthetic.csv

# Classical ML: category and action models
cd classical-ml && PYTHONPATH=src python -m train_email_ml
```

Models go to `text-encoders/models/` and `classical-ml/artifacts/`. Claude is
not trained: its prompt, sender rules and guardrails are in
`claude/config.yaml`. Each folder's README has the other options
([`text-encoders`](text-encoders/README.md),
[`classical-ml`](classical-ml/README.md), [`claude`](claude/README.md)).

---

## Results

All comparison tables are in
[`docs/MODEL_COMPARISON.md`](docs/MODEL_COMPARISON.md): the classical-ML model
comparison, the synthetic-data ablation, the encoder-head comparison, the
shared encoder-vs-ML holdout, and the four-method quality and operational
results.

To run the comparison again:

```bash
python evaluation/quality.py --model all
python evaluation/performance.py --model all
```

Claude calls cost money, so use `--claude-limit N` to cap them.

The classical-ML reports (model comparison, tuning, synthetic ablation) come
from:

```bash
cd classical-ml && PYTHONPATH=src python -m experiments compare   # also: tune, ablation
```

---

## Folder map

```
email-sorter/            NusBox app: Flask backend, React frontend, sign-in pages, tests
email-sorter/llm-reply/  Reply drafts used by the app (Claude), plus their evaluation
text-encoders/           BGE/E5 heads and DistilBERT fine-tunes
classical-ml/            TF-IDF + LinearSVC / ComplementNB
claude/                  Claude backend (rules -> Claude -> guardrails)
evaluation/              Shared quality and operational evaluation
data/                    synthetic.csv, NUS academic calendar (labels.csv is gitignored)
docs/                    Result tables
```

More detail:

- [`email-sorter/README.md`](email-sorter/README.md): app settings, mail
  sources, Power Automate, accounts, backends, API.
- [`email-sorter/frontend/README.md`](email-sorter/frontend/README.md): the
  React app.
- [`evaluation/README.md`](evaluation/README.md): how the four methods are
  scored.

---

## Checks

With the virtual environment active:

```bash
make test    # all Python tests (app, Claude backend, reply drafts)
make lint    # ruff: undefined names and unused imports
make build   # typecheck and build the frontend
make check   # lint + test + build, the same as CI
```
