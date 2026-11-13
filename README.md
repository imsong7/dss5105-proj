# NusBox — DSS5105 Track 4, Group 13

NusBox is an email assistant for NUS students. It reads a student's Outlook
mail, sorts each message into a **category** and an **action**, scores its
priority, and pulls out deadlines, events and job posts into a Today page and a
calendar.

The repository also holds the model work behind it: four ways to classify the
same emails, and one evaluation that compares them.

| Method | Folder | What it uses |
|---|---|---|
| Text encoders | `text-encoders/` | Frozen BGE / E5 heads, plus DistilBERT fine-tunes |
| Classical ML | `classical-ml/` | TF-IDF + LinearSVC / ComplementNB |
| Llama | `email-sorter/` | Llama 3.1 8B through Ollama (built into the app) |
| Claude | `claude/` | Anthropic Claude with sender rules and guardrails |

The app ships with `hybrid_claude`: the classical-ML model picks the category
and Claude picks the action.

---

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

`run.py` rebuilds the React frontend when its code has changed, so it needs
`npm` and `make install` done once.

To run only the app (no model training or evaluation), install the much
lighter `requirements-app.txt` instead of `requirements.txt`:

```bash
pip install -r requirements-app.txt
(cd email-sorter/frontend && npm ci)
```

### Trying it from a fresh clone

Two things are not in the repository: the Anthropic API key, and the
classical-ML model, which is trained on labelled student email and kept
private (`classical-ml/artifacts/` is gitignored).

- **Without either:** the app still runs. On the sign-in page choose
  "Use an Outlook token instead" and paste a Graph Explorer token (or sign up
  at `/register`). Mail loads with its deadlines, calendar, course pages and
  job posts, which do not need a model; sorting says the model is not ready.
  Only NUS addresses are accepted by default; set `ALLOWED_EMAIL_DOMAINS` in
  `email-sorter/.env` for others.
- **With an `ANTHROPIC_API_KEY`** in `claude/.env`: start with
  `--backend claude` to sort, rate and draft replies with Claude alone.
- **Without a key, with the full `requirements.txt`:** `--backend encoder`
  uses the committed encoder heads (it downloads the BGE/E5 encoders from
  Hugging Face on first use).

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

A fresh clone includes the trained encoder heads but not the classical-ML
artifacts (`classical-ml/artifacts/`, gitignored) or `data/labels.csv`. Until
you train those, start with `--backend encoder`. The dashboard shows which
backend is ready.

---

## Training the methods

### Text encoders

```bash
python text-encoders/train.py --check-only
python text-encoders/train.py --task category
python text-encoders/train.py --task action --synthetic data/synthetic.csv
```

Models are written to `text-encoders/models/{task}_{head,full}/`. See
[`text-encoders/README.md`](text-encoders/README.md).

### Classical ML

```bash
cd classical-ml
PYTHONPATH=src python -m data_tools convert-labels
PYTHONPATH=src python -m train_email_ml
PYTHONPATH=src python -m experiments compare
PYTHONPATH=src python -m experiments tune
PYTHONPATH=src python -m experiments ablation
```

Models and reports go to `classical-ml/artifacts/` and `classical-ml/reports/`.
See [`classical-ml/README.md`](classical-ml/README.md).

### Claude

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > claude/.env
```

See [`claude/README.md`](claude/README.md).

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

---

## Privacy and data

The app handles real student mail, so this is where that mail goes.

- **Sent to Anthropic (Claude API):** with the `hybrid_claude` or `claude`
  backend, each email's subject and text (up to 4,000 characters together) and
  its received date are sent to classify it. A reply draft sends the email (up to 8,000
  characters) and the student's name. The `encoder`, `ml` and `llama`
  backends run entirely on this computer.
- **Stays on this computer:** accounts, pushed mail, results, corrections,
  events and settings are files under `email-sorter/private/` (gitignored;
  the accounts file is readable only by the user running the app). Poster
  images are read locally (Tesseract and OpenCV).
- **Kept in memory only:** Microsoft Graph tokens. A pasted token stays in the
  browser tab and goes with each request; a token used to sign in or to send a
  reply is kept in server memory for at most two hours. Tokens are never
  written to disk.
- **The mailbox is read, not changed.** The only thing the app sends from it
  is a reply, and only when the student presses Send.
- **Reachable from outside only with `--tunnel`.** The app listens on
  `127.0.0.1`; ngrok exposes it (with sign-in) so Power Automate and phones can
  reach it. The `.ics` calendar feed is readable by anyone with its secret
  link, which the student can rotate.

---

## Folder map

```
email-sorter/            NusBox app: Flask backend, React frontend, sign-in pages, tests
email-sorter/llm-reply/  Reply-draft generator and its evaluation
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
