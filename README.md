# dss5105-proj — Email Classification Project

**How to work together**
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

---

The repo has three parts:

| Folder | Purpose |
|--------|---------|
| `email-sorter/` | The Flask app. Fetches emails, sorts them with Llama (Ollama) or BERT, and compares backends side by side. |
| `bert/` | BERT experiment/training code. Trains and compares DistilBERT fine-tunes and frozen-encoder heads on labeled email data. |
| `evaluation/` | Offline quality and operational benchmarks: OOF macro-F1 with bootstrap CIs, plus latency, memory, token, energy, and consistency measurements. |

---

## Quick start

**Run the email-sorter app** (Windows, VS Code terminal):
```bash
cd email-sorter
python -m venv .venv
.venv\Scripts\Activate.ps1   # or: source .venv/bin/activate  (Mac/Linux)
pip install -r requirements.txt
copy .env.example .env
python run.py
# Open http://127.0.0.1:5000
```

Pick **Llama** or **BERT** in the sidebar — no `--backend` flag is required.
`MODEL_BACKEND` in `.env` only sets the initial default. Llama needs
`ollama pull llama3.1:8b` and a running Ollama; BERT needs trained models
(see below).

The app has two pages:

| Page | Purpose |
|------|---------|
| `/` | Sort one mailbox batch with a selected backend, filter by category/action, retry failures. |
| `/compare` | Run the same batch through several backends, compare per-email labels and latency, and export CSV. |

**Train BERT models** (from repo root, `.venv` activated):
```bash
# Validate labels
python bert/train.py --review bert/data/labels.csv --check-only

# Frozen-encoder head (recommended — tiny, fast) -> bert/models/{task}_head/
python bert/train.py --review bert/data/labels.csv --mode head --task category
python bert/train.py --review bert/data/labels.csv --mode head --task action \
    --encoder e5-small-multi --synthetic bert/data/synthetic.csv

# DistilBERT fine-tune -> bert/models/{task}_full/
python bert/train.py --review bert/data/labels.csv --mode full --task both
```

See `bert/README.md` for full BERT training docs.

**Evaluate models** (quality + operational metrics):
```bash
# 5-fold out-of-fold predictions + 95% bootstrap CIs (deployed configuration)
python evaluation/offline_f1.py

# Real-only baseline
python evaluation/offline_f1.py --no-synthetic

# Operational benchmark: latency, memory, tokens, energy, consistency
# (needs Ollama for the Llama backend)
python evaluation/operational_benchmark.py

# Unit tests for both evaluators
python -m unittest evaluation.test_offline_f1 -v
python -m unittest evaluation.test_operational_benchmark -v
```

The operational benchmark uses two optional packages; install them once:
```bash
python -m pip install -r evaluation/requirements.txt
```

Results are written to `evaluation/results/` as flat CSV/JSON/TXT files. See
`evaluation/README.md` for the methodology and caveats.

---

## Where things are

### `email-sorter/` — the app
```
email-sorter/
  app/
    taxonomy.py         # Category + action label definitions (single source of truth)
    classifier_base.py  # BaseClassifier, backend registry, factory
    classifier.py       # Llama/Ollama backend
    bert_classifier.py  # BERT backend (lazy model loading)
    config.py           # Settings (backend default, model name, port, body limit)
    server.py           # Flask app + API routes
    models.py           # Email / Classification data models
    rules.py            # Deterministic sender rules (Canvas -> category "canva")
    textutil.py         # Text helpers
    providers/          # Email fetchers (IMAP, Microsoft Graph, base)
  static/
    style.css
    common.js           # API, formatting, backend registry helpers
    sorter.js           # Sorter page
    compare.js          # Compare page
  templates/
    base.html           # Shared layout and nav
    index.html          # Sorter page
    compare.html        # Compare page
  run.py                # Entry point: python run.py
  requirements.txt      # Covers both Llama and BERT backends
  .env.example / .env
```

### `bert/` — BERT training & experiments
```
bert/
  train.py                  # unified trainer (--mode head|full)
  src/
    __init__.py
    data.py                 # data loading, validation, split, synthetic
    model.py                # encoder, head training, EmbedPredictor
  data/
    labels.csv              # hand-labeled real emails
    synthetic.csv           # synthetic emails (seed-fixed)
  make_synthetic.py         # regenerate synthetic.csv
  README.md                 # BERT-specific docs

  models/
    action_head/            # frozen encoder head for action (recommended)
    action_full/            # distilbert fine-tune for action
    category_head/          # frozen encoder head for category (recommended)
    category_full/          # distilbert fine-tune for category

  results/
    compare_head_summary.txt
    compare_head_runs.csv
    compare_full_summary.txt
    compare_full_summary.csv
    compare_full_runs.csv
```

### `evaluation/` — offline and operational evaluation
```
evaluation/
  offline_f1.py             # OOF predictions + stratified bootstrap CIs
  operational_benchmark.py  # latency, memory, tokens, energy, consistency
  test_offline_f1.py
  test_operational_benchmark.py
  requirements.txt          # optional benchmark deps (psutil, codecarbon)
  README.md                 # methodology and current results
  results/
    offline_f1_summary.csv
    offline_f1_per_class.csv
    offline_f1_confusion.csv
    offline_f1_oof_predictions.csv
    offline_f1_manifest.json
    offline_f1_report.txt
    operational_benchmark_summary.csv
    operational_benchmark_runs.csv
    operational_benchmark_consistency.csv
    operational_benchmark_length.csv
    operational_benchmark_manifest.json
    operational_benchmark_report.txt
```

Large `model.safetensors` files stay on disk but are ignored by Git.

---

## Which model to use in the app

Choose the backend in the UI. BERT loads
`EmbedPredictor("bert/models/<task>_head")` for each task.

| Task | Recommended model | OOF macro-F1 (95% CI) | Why |
|------|-------------------|-----------------------|-----|
| Category | `bert/models/category_head` (bge-small-en) | **0.844** [0.780, 0.905] model-only; **0.870** [0.813, 0.919] end-to-end | Best accuracy, tiny file |
| Action | `bert/models/action_head` (e5-small-multi + synthetic) | **0.795** [0.707, 0.871] real+synthetic; 0.697 real-only | Synthetic helps the head; tiny file |

These are 5-fold out-of-fold estimates from `evaluation/offline_f1.py`, which
uses all labelled emails instead of the old 27-row test split. The historical
split results remain in `bert/README.md`.

Operational benchmark on a 30-email stratified sample, 5 runs per email, seed
42, CodeCarbon enabled, and a cold Ollama start:

| Backend | Warm p50 / p95 | Peak memory | Energy | 5-run consistency | 200-char vs full |
|---------|----------------|-------------|--------|-------------------|------------------|
| Llama 3.1 8B | 3,298 / 5,334 ms | 5.7 GB | 0.00220 kWh | 1.000 | 0.767 |
| BERT heads | 33.5 / 41.6 ms | 972 MB | 0.000042 kWh | 1.000 | 0.967 |

See `evaluation/README.md` for cold-start, model-size, token, and caveat details.
See `bert/README.md` for training details.

---

## Other files at root

| File | Purpose |
|------|---------|
| `VERIFICATION.md` | Historical real-data verification report (bugs found, test results, remaining work) |
| `CHANGES.md` | Change log for email-sorter |
| `.gitignore` | Ignores venv, `__pycache__`, `.DS_Store`, `emails.csv`, model outputs |
