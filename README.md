# dss5105-proj — Email Classification Project

**How to work together** 
```bash
# 1. Start fresh from updated main
git clone git@github.com:imsong7/dss5105-proj.git
cd dss5105-proj

git switch main
git pull origin main
git switch -c feature/your-name

# 2. Do work, then save locally
git add .
git commit -m "Describe your changes"

# 3. Get latest main updates into your feature branch (Crucial!)
git fetch origin
git merge origin/main

# 4. Push to GitHub
git push -u origin feature/your-name
```

---


One folder per method:

| Folder | Purpose |
|--------|---------|
| `email-sorter/` | The running Flask app (Sprint 1 prototype). Fetches emails, classifies them with a local Llama model via Ollama, and shows results on a web page. |
| `text-encoders/` | BERT experiment/training code. Trains and compares DistilBERT fine-tunes and frozen-encoder heads on labeled email data. |
| `classical-ml/` | Classical ML baselines (TF-IDF + LinearSVC / ComplementNB). Compares 8 models, tunes hyperparameters, and ablates synthetic data. |
| `inbox-sorter/` | Claude method. Rules → Anthropic API → guardrails, plus a small dashboard. |

The shared evaluation for all four methods lives in `evaluation/`.

---

## How to work together

```bash
# 1. Start fresh from updated main
git switch main
git pull origin main
git switch -c feature/your-name

# 2. Do work, then save locally
git add .
git commit -m "Describe your changes"

# 3. Get latest main updates into your feature branch (Crucial!)
git fetch origin
git merge origin/main

# 4. Push to GitHub
git push -u origin feature/your-name
```

## Quick start

**Run the email-sorter app** (Windows, VS Code terminal):
```bash
cd email-sorter
python -m venv .venv
.venv\Scripts\Activate.ps1   # or: source .venv/bin/activate  (Mac/Linux)
pip install -r requirements.txt
copy .env.example .env
ollama pull llama3.1:8b
python run.py
# Open http://127.0.0.1:5000
```

**Train text-encoder models** (from repo root, `.venv` activated):
```bash
# Validate labels
python text-encoders/train.py --check-only

# Frozen-encoder heads (recommended — tiny, fast) -> text-encoders/models/{task}_head/
python text-encoders/train.py --task category
python text-encoders/train.py --task action --synthetic data/synthetic.csv
```

See `text-encoders/README.md` for full training docs.

**Train classical ML baselines** (from repo root):
```bash
cd classical-ml
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-ml.txt

# labels.xlsx is not committed (real email data). Get it from the team first.
cp "/path/to/labels.xlsx" ../data/labels.xlsx
PYTHONPATH=src python -m data_tools convert-labels

PYTHONPATH=src python -m train_email_ml       # main training + metrics
PYTHONPATH=src python -m experiments compare  # 8-model comparison
PYTHONPATH=src python -m experiments tune     # hyperparameter search
PYTHONPATH=src python -m experiments ablation # synthetic vs real-only
```

See `classical-ml/README.md` for data format, results, and evaluation caveats.

---

## Where things are

### `email-sorter/` — the app
```
email-sorter/
  app/
    taxonomy.py    # Category + action label definitions (single source of truth)
    classifier.py  # Llama/Ollama classification logic
    config.py      # Settings (model name, port, body char limit)
    server.py      # Flask app + API routes
    models.py      # Email / Classification data models
    providers/     # Email fetchers (IMAP, Microsoft Graph, base)
    textutil.py    # Text helpers
  run.py           # Entry point: python run.py
  rules.py         # Deterministic sender rules (Canvas → category "canva")
  templates/index.html   # Frontend web page
  requirements.txt
  .env.example / .env
```

### `text-encoders/` — encoder training & experiments
```
text-encoders/
  train.py                 # unified trainer (--mode head|full)
  src/
    data.py                # data loading, validation, splits, synthetic checks
    model.py               # Encoders, head training, EmbedPredictor
  models/
    action_head/           # frozen encoder head for action (recommended)
    action_full/           # DistilBERT fine-tune for action
    category_head/         # frozen encoder head for category (recommended)
    category_full/         # DistilBERT fine-tune for category
  results/
    compare_head_summary.txt / .csv
    compare_full_summary.txt / .csv
    compare_head_runs.csv / compare_full_runs.csv
  README.md                # encoder-specific docs
```

### `classical-ml/` — classical ML baselines
```
classical-ml/
  src/
    train_email_ml.py       # main trainer (repeated CV, metrics, models)
    comparison.py           # 8-model comparison + majority baseline
    experiments.py          # compare / tune / ablation runner
    data_tools.py           # workbook conversion + synthetic generator
  reports/                  # committed aggregate reports
    model_comparison.md/.csv
    hyperparameter_tuning.md/.csv
    ablation_synthetic.md/.csv
  artifacts/                # local only (gitignored): models, predictions, splits
  requirements-ml.txt
  README.md                 # ML docs, results, caveats
```

Selected baselines: `linear_svm` for `email_category` (CV macro-F1 0.906) and
`complement_nb_balanced` + synthetic for `required_action` (CV macro-F1 0.688).
`data/labels.csv` and `classical-ml/artifacts/` are intentionally not committed
because they contain real email content.

---

## Which model to use in the app

| Task | Recommended model | Why |
|------|-------------------|-----|
| Category | `text-encoders/models/category_head` (bge-small-en) | Best accuracy (0.865 macro-F1), tiny file |
| Action | `text-encoders/models/action_head` (e5-small-multi + synthetic) | Best accuracy (0.511 macro-F1), tiny file |

The app loads models via `EmbedPredictor("text-encoders/models/<task>_head")`. See
`text-encoders/README.md`. The classical ML pipelines are also selectable in the
app through `classical-ml/artifacts/`.

---

## Other files at root

| File | Purpose |
|------|---------|
| `VERIFICATION.md` | Real-data verification report (bugs found, test results, remaining work) |
| `CHANGES.md` | Change log for email-sorter |
| `preprocess_fix.diff` | Patch for `preprocess.py` pandas-3 compatibility |
| `.gitignore` | Ignores venv, `__pycache__`, `.DS_Store`, `emails.csv`, model outputs |

---

## Comparing the four methods

Two scripts, one metric set each:

| script | metrics |
|--------|---------|
| `evaluation/quality.py` | accuracy, macro F1 |
| `evaluation/performance.py` | warm latency (p50), peak memory, tokens, invalid-output rate |

See [`evaluation/README.md`](evaluation/README.md) for the full protocol, data
counts, outputs and current results.

| `--model` | Method | Where it runs |
|-----------|--------|---------------|
| `llm` | Llama 3.1 8B via Ollama | `email-sorter/app/llama_classifier.py` |
| `bert` | Frozen text-encoder heads | `email-sorter/app/bert_classifier.py` |
| `ml` | TF-IDF + LinearSVC / ComplementNB | `email-sorter/app/ml_classifier.py` |
| `claude` | Anthropic Claude API | `inbox-sorter/` pipeline (rules → Claude → guardrails) |

```bash
# all four methods on the same 30-emails sample
python evaluation/performance.py --model all

# only two, or one
python evaluation/performance.py --model bert ml
python evaluation/performance.py --model claude --claude-limit 10

# skip the paid API calls
python evaluation/performance.py --model llm bert ml
```

The Claude backend calls the Anthropic API, so it costs money: it needs
`ANTHROPIC_API_KEY` in `inbox-sorter/.env` and the `anthropic` package.
`--claude-limit N` caps the number of emails sent to the API (the other backends
still use the full sample, so the table's `N` column shows each sample size).

### Quality evaluation

```bash
python evaluation/quality.py --model all
python evaluation/quality.py --model claude --claude-limit 50
```

The `ml` family reads the shared review CSV `data/labels.csv` by default (real
email data, not committed). To use the team workbook instead, point
`ML_LABELS_XLSX` at it; `ML_LABELS_CSV` overrides the CSV path:

```bash
ML_LABELS_XLSX=/path/to/labels.xlsx python evaluation/quality.py --model all
```

### Reading the numbers

Encoder and ML use out-of-fold predictions, so no email is scored by a model
that saw it. The LLM families are zero-shot, which is a property of the methods
rather than a bug in the comparison.

The Claude column is **the inbox-sorter method as configured**, not the same
prompt with a different model: it uses its own label wording, it breaks action
ties in a different order ("Needs a reply" before "Needs an action"), and it
adds a confidence guardrail and a no-reply sender rule. The gap between Claude
and Llama therefore measures the two systems, not only the two models.

### Rubric alignment (measured, not guessed)

The two teams' label definitions disagreed on one line, and it was worth 12
accuracy points. The inbox-sorter called a dated event a `Reminder`
("deadline, **event**, due date"); the shared review calls it
`No immediate action`. Claude was answering the inbox-sorter's rubric and being
scored against the review's rubric.

Few-shot examples did **not** fix the gap (tested: 28 -> 27 of 38 correct). The
definition was the problem, so that is what changed.

`inbox-sorter/config.yaml` now carries the aligned wording. On the 134
action-usable emails, Claude's action accuracy went from **0.784 to 0.888**,
which makes it the best action classifier in the comparison. The trade-off:
reminder recall dropped (1.00 -> 0.73) while no_immediate_action recall rose
(0.76 -> 0.92). The per-class numbers are kept in
`evaluation/results/rubric_alignment.csv`. The lesson for the write-up: the
rubric is part of the method, so it has to be measured too.

`evaluation/inbox_sorter.py` adapts the inbox-sorter to both scripts: it loads
the inbox-sorter package under an alias (its `src`/`app` names would otherwise
shadow the other projects) and maps the inbox-sorter labels onto the
email-sorter taxonomy so all four methods are comparable:

| inbox-sorter | email-sorter |
|--------------|--------------|
| FoS General | `general` |
| Career | `career` |
| Medical | `medical` |
| Promotions | `promotional` |
| Canvas | `canva` |
| Others | `others` |
| Needs a reply | `needs_reply` |
| Needs an action | `needs_action` |
| Reminder | `reminder` |
| No action needed | `no_immediate_action` |
| Further review | `no_immediate_action` (fallback, same as the ML mapping) |
