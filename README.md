# DSS5105 — Email Classification Project

This repository compares four ways to sort a student's email:

| Method | Folder | What it uses |
|---|---|---|
| Text encoders | `text-encoders/` | Frozen BGE / E5 heads, plus DistilBERT fine-tunes |
| Classical ML | `classical-ml/` | TF-IDF + LinearSVC / ComplementNB |
| Llama | `email-sorter/` | Llama 3.1 8B through Ollama (built into the app) |
| Claude | `claude/` | Anthropic Claude with sender rules and guardrails |

`email-sorter/` is the shared Flask app: it hosts the dashboard, the mail
sources, and every classifier backend. `evaluation/` scores all four methods
on the same emails.

---

## Quick start

Use one virtual environment at the repo root.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp email-sorter/.env.example email-sorter/.env
python email-sorter/run.py
# open http://127.0.0.1:5000
```

If port 5000 is already in use (macOS Control Center uses it), add
`--port 5001`:

```bash
python email-sorter/run.py --port 5001
```

A fresh clone includes the trained encoder heads but not the classical-ML
artifacts (`classical-ml/artifacts/`, gitignored) or `data/labels.csv`. Until
you train those, start with `--backend encoder`, or use
`--backend llama` after `ollama pull llama3.1:8b`.

### Default behaviour

- **Mail source:** `graphtoken` — paste a Microsoft Graph token in the dashboard
  popup. No app login is needed.
- **Backend:** `hybrid_claude` — classical-ML category + Claude action.
- **Home page:** dashboard v2 (`/dashboard-v2` is also available).

For Power Automate instead:

```bash
python email-sorter/run.py --port 5001 --provider powerautomate
```

That mode adds a per-user app login and starts ngrok automatically.

### Requirements for each backend

| Backend | Needs |
|---|---|
| `hybrid_claude` (default) | `classical-ml/artifacts/email_category_model.joblib` + `ANTHROPIC_API_KEY` in `claude/.env` |
| `hybrid` | ML category model + `text-encoders/models/action_head/` |
| `encoder` | `text-encoders/models/{category,action}_head/` |
| `ml` | both classical-ML artifacts |
| `llama` | `ollama pull llama3.1:8b` and Ollama running |
| `claude` | `ANTHROPIC_API_KEY` in `claude/.env` |

The app shows which backend is ready on the dashboard. If a model is missing,
train it with the commands below or choose another backend.

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

Add the key to `claude/.env`:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > claude/.env
```

The Claude backend is already wired into the app; no separate dashboard is
needed. See [`claude/README.md`](claude/README.md).

---

## Results

All committed comparison tables are in
[`MODEL_COMPARISON.md`](MODEL_COMPARISON.md):

- classical-ML model comparison (8 models, category and action),
- synthetic-data ablation,
- encoder-head comparison,
- shared encoder-vs-ML holdout,
- four-method quality and operational results (older run plus the latest
  Claude figures).

For a fresh comparison:

```bash
python evaluation/quality.py --model all
python evaluation/performance.py --model all
```

These commands cover all four families. Claude calls cost money, so use
`--claude-limit N` to cap them. Run either script with `--help` to see all
options.

---

## Folder map

```
email-sorter/     Flask app, dashboard, auth, mail sources, backends
text-encoders/    BGE/E5 heads and DistilBERT fine-tunes
classical-ml/     TF-IDF + LinearSVC / ComplementNB
claude/           Claude backend (rules -> Claude -> guardrails)
evaluation/       Shared quality and operational evaluation
data/             Shared synthetic.csv and local labels.csv (labels gitignored)
requirements.txt  One dependency file for the whole repo
```

Details:

- [`email-sorter/README.md`](email-sorter/README.md) — app setup, mail sources,
  Power Automate, login, dashboard, API.
- [`text-encoders/README.md`](text-encoders/README.md) — encoder training.
- [`classical-ml/README.md`](classical-ml/README.md) — classical ML training.
- [`claude/README.md`](claude/README.md) — Claude backend.
- [`evaluation/README.md`](evaluation/README.md) — quality and performance
  evaluation for all four methods.
- [`MODEL_COMPARISON.md`](MODEL_COMPARISON.md) — all result tables.

---

## Tests

```bash
# app
(cd email-sorter && pytest -q)

# Claude backend
(cd claude && pytest -q)

# evaluation
python -m unittest evaluation.test_evaluation
```

---

## Working with git

```bash
git switch main
git pull origin main
git switch -c feature/your-name

# after making changes
git add .
git commit -m "Describe your changes"
git fetch origin
git merge origin/main
git push -u origin feature/your-name
```
