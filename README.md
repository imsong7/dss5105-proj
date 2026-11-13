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

## Quick start

Use one virtual environment at the repo root.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
make install                       # Python packages + frontend packages

cp email-sorter/.env.example email-sorter/.env
python email-sorter/run.py
# open http://127.0.0.1:5001
```

`run.py` rebuilds the React frontend when its code has changed, so it needs
`npm` (Node 22) and `make install` done once.

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
