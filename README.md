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


Three parts live in this repo:

| Folder | Purpose |
|--------|---------|
| `email-sorter/` | The running Flask app (Sprint 1 prototype). Fetches emails, classifies them with a local Llama model via Ollama, and shows results on a web page. |
| `bert/` | BERT experiment/training code. Trains and compares DistilBERT fine-tunes and frozen-encoder heads on labeled email data. |
| `ML/` | Classical ML baselines (TF-IDF + LinearSVC / ComplementNB). Compares 8 models, tunes hyperparameters, and ablates synthetic data. |

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

**Train BERT models** (from repo root, `.venv` activated):
```bash
# Validate labels
python bert/train.py --review bert/data/labels.csv --check-only

# Train frozen-encoder head (recommended — tiny, fast) -> bert/models/{task}_head/
python bert/train.py --review bert/data/labels.csv --encoder bge-small-en --task category
python bert/train.py --review bert/data/labels.csv --encoder e5-small-multi --task action \
    --synthetic bert/data/synthetic.csv
```

See `bert/README.md` for full BERT training docs.

**Train classical ML baselines** (from repo root):
```bash
cd classical-ml
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-ml.txt

# ../data/labels.csv is not committed (real email data). Convert the team's
# workbook once, or place labels.csv/labels.xlsx in ../data/ yourself.
cp "/path/to/labels.xlsx" ../data/labels.xlsx
PYTHONPATH=src python -m data_tools convert-labels

PYTHONPATH=src python -m train_email_ml       # models + metrics -> artifacts/
PYTHONPATH=src python -m experiments compare  # model comparison -> reports/
PYTHONPATH=src python -m experiments tune     # hyperparameter search -> reports/
PYTHONPATH=src python -m experiments ablation # synthetic vs real-only -> reports/
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

### `bert/` — BERT training & experiments
```
bert/
  train.py                 # unified trainer (--mode head|full)
  src/                     # Python package (data.py, model.py)
    __init__.py
    data.py                # data loading, validation, split, synthetic
    model.py               # Encoder, head training, EmbedPredictor
  data/                    # data files
    labels.csv             # Hand-labeled real emails (~80 usable)
    synthetic.csv          # 91 synthetic emails (seed-fixed)
    labels_review_provisional.csv
  make_synthetic.py        # Regenerate synthetic.csv
  preprocess.py            # Legacy — merges Excel sheets into labels.csv (data_1012.xlsx is gone)
  label.html               # Browser-based labeling UI
  README.md                # BERT-specific docs

  models/
    action_head/           # frozen encoder head for action (recommended)
    action_full/           # distilbert fine-tune for action (~512MB)
    category_head/         # frozen encoder head for category (recommended)
    category_full/         # distilbert fine-tune for category (~512MB)

  results/
    compare_head_summary.txt    # head mode comparison results
    compare_head_summary.csv
    compare_head_runs.csv
    compare_full_summary.txt    # full mode comparison results
    compare_full_summary.csv
    compare_full_runs.csv
```

### `ML/` — classical ML baselines
```
ML/
  train_email_ml.py                # main trainer (repeated CV, metrics, models)
  compare_models.py                # 8-model comparison + majority baseline
  tune_models.py                   # TF-IDF / classifier hyperparameter grid
  ablation_synthetic.py            # synthetic vs real-only for required_action
  generate_synthetic_action_data.py
  requirements-ml.txt
  README.md                        # ML docs, results, caveats
  synthetic_required_action.csv    # committed synthetic action rows
  model_comparison.md/.csv
  hyperparameter_tuning.md/.csv
  ablation_synthetic.md/.csv
  ml_outputs/                      # local only (ignored): metrics, plots, joblib models
```

Selected baselines: `linear_svm` for `email_category` (CV macro-F1 0.906) and
`complement_nb_balanced` + synthetic for `required_action` (CV macro-F1 0.688).
`ML/labels.xlsx` and `ml_outputs/` are intentionally not committed because they
contain real email content.

---

## Which model to use in the app

| Task | Recommended model | Why |
|------|-------------------|-----|
| Category | `bert/models/category_head` (bge-small-en) | Best accuracy (0.865 macro-F1), tiny file |
| Action | `bert/models/action_head` (e5-small-multi + synthetic) | Best accuracy (0.511 macro-F1), tiny file |

The app loads models via `EmbedPredictor("bert/models/<task>_head")`. See `bert/README.md`.
The `ML/` classical baselines are experiments and are not yet wired into the Flask app.

---

## Other files at root

| File | Purpose |
|------|---------|
| `VERIFICATION.md` | Real-data verification report (bugs found, test results, remaining work) |
| `CHANGES.md` | Change log for email-sorter |
| `preprocess_fix.diff` | Patch for `preprocess.py` pandas-3 compatibility |
| `.gitignore` | Ignores venv, `__pycache__`, `.DS_Store`, `emails.csv`, model outputs |
