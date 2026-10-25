# Changes made to email-sorter

## 1. Fixed class name conflict (deadline_mentioned → reminder)
- **app/taxonomy.py**: Renamed `deadline_mentioned` key to `reminder` in `REPLY_NATURE`. Label and description unchanged.
- **templates/index.html**: Updated CSS selector from `[data-k=deadline_mentioned]` to `[data-k=reminder]` to keep styling consistent.

Verified: `REPLY_NATURE.keys()` now include `reminder` instead of `deadline_mentioned`.

## 2. Codebase cleanup
- **email-sorter/.gitignore**: Added `email_cl/` to ignore the local virtual environment.
- **Removed unnecessary artifacts**: Deleted `email_cl/` directory (committed venv), all `__pycache__` folders, and all `*.pyc` files. These are generated files that shouldn't be tracked.

## 3. What remains
- Core application code (`app/`, `run.py`, `templates/`, `static/`)
- Configuration files (`requirements.txt`, `.env.example`, `.gitignore`, `README.md`)
- `.env` (local defaults) - still present; typically not committed but fine for local use

## 4. Multi-page UI and backend registry
- Added a `/compare` page that runs the same mailbox batch through several
  backends, reports per-backend latency (total/average/median/p95, with optional
  warm-up excluded), shows pairwise label agreement, and exports CSV.
- Split the frontend into `templates/base.html` + `index.html` + `compare.html`
  and `static/style.css` + `common.js` + `sorter.js` + `compare.js`.
- Added `BACKEND_INFO` to `app/classifier_base.py`; `/api/backends` exposes the
  registry so future ML/agent backends appear in both pages without frontend
  changes.
- Sorter backend buttons are now rendered from the registry; the selected
  backend is saved in the browser, while `MODEL_BACKEND`/`--backend` only set the
  initial server default.
- Added cancel/retry, request timeouts, validation, progress cleanup, and a
  single human-readable latency summary per batch.

The codebase is now cleaner and ready for integration of a custom ML model or
agent backend.

## 5. Offline evaluation
- Added `evaluation/offline_f1.py`: 5-fold stratified out-of-fold predictions
  for the frozen BERT heads, with 95% stratified-bootstrap confidence intervals.
- Reports category model-only (132 rows), category end-to-end with the Canvas
  rule (200 rows), action (134 rows), and both-label exact match (133 unique
  emails; one action row has category `__skip__`).
- Defaults to the deployed configuration: category real-only, action
  real+synthetic. `--no-synthetic` gives the real-only baseline.
- Added `evaluation/test_offline_f1.py`, `evaluation/README.md`, and flat result
  files under `evaluation/results/`.
- Updated the README model table to quote OOF macro-F1 instead of the old
  27-row test split.

## 6. Operational benchmark
- Added `evaluation/operational_benchmark.py`: cold/warm latency, load time,
  process and Ollama RSS, model size, token use, CodeCarbon energy, 5-run
  consistency, raw invalid-format rate, and first-200-char vs full-input
  agreement.
- Added a raw-capturing Llama chain (`with_structured_output(..., include_raw=True)`)
  so invalid JSON/labels are counted before Pydantic coercion.
- Added `evaluation/test_operational_benchmark.py` and
  `evaluation/requirements.txt` (`psutil`, `codecarbon`).
- Ran a 30-email stratified sample with 5 runs per email. Llama: warm p50/p95
  3,298/5,334 ms, 5.7 GB peak, 0.00220 kWh, 0 invalid formats, consistency 1.000.
  BERT: warm p50/p95 32.9/40.8 ms, 921 MB peak, 0.000032 kWh, consistency 1.000.
- Updated the README with operational commands and headline results.

## 7. Faster BERT startup
- Added `_from_pretrained` in `bert/src/model.py`: it tries the local Hugging
  Face cache with `local_files_only=True` and falls back to the normal download
  path on a cache miss.
- This removes the hub metadata round-trip that dominated BERT startup. BERT
  load dropped from 6,863 ms to 3,398 ms in the operational benchmark; a smaller
  BERT-only smoke run measured about 2.3 s.
- Regenerated the BERT operational results and report. Llama results are retained
  from the earlier run because only the BERT loader changed.
- Made `render_report` ignore NaN `error` cells when reading a summary CSV.

## 8. Align BERT app input with evaluation
- `BertClassifier` now uses `Email.body` first and falls back to `Email.preview`.
  The providers keep only a 200-character preview, so the app previously
  classified a shorter input than the offline evaluator and the standalone
  `EmbedPredictor` example.
- The operational benchmark now counts BERT tokens from the same body-first
  input, and its report uses the configured `--short-chars` value instead of
  hardcoding 200.
- Added `evaluation/test_bert_classifier.py` for body/preview selection and
  classification routing.
- Updated the evaluation and root READMEs. No model retraining was needed; the
  offline OOF scores already use the full body and are unchanged.

## 9. Repository cleanup
- Removed the unused legacy Excel review pipeline and `--export-review` /
  `--prefill` options. `bert/data/labels.csv` is now the source of truth.
- Removed the unused `bert/src/__init__.py` re-export list.
- Moved duplicated evaluation helpers into `evaluation/__init__.py`.
- Shared the Llama chain construction between the app and the operational
  benchmark, and shared mailbox/credential/classification helpers in the
  frontend.
- Fixed full-mode synthetic training (`random_state`), `make_synthetic.py`
  output path, BERT readiness/partial-load reporting, Ollama URL parsing, the
  hardcoded Canvas count, and CSV formula-injection escaping.
- Stopped tracking generated full-model directories and head prediction CSVs;
  the files remain locally and are ignored by Git. Removed stale
  `VERIFICATION.md`.

## 10. Simpler trainer CLI
- Reduced `bert/train.py` from 16 flags to 8: mode, task, review, encoder,
  synthetic, synthetic-tasks, compare-seeds, and check-only.
- `--review` now defaults to `bert/data/labels.csv`; output paths are fixed at
  `bert/models` and `bert/results`.
- Removed the full-mode model/epochs/lr overrides, output-dir overrides,
  `--allow-missing-labels`, `--encoders`, and `--tfidf-only`.
- Head training now defaults to bge-small-en for category and e5-small-multi
  for action; `--encoder` overrides both.
- Shortened the trainer docstring and `--help` descriptions, and removed
  redundant setup/summary lines.

## 11. BERT model cleanup
- Removed the unused `labels` argument from `train_once`, dropped redundant
  local aliases, and simplified/annotated helpers in `bert/src/model.py`.

## 12. Evaluation cleanup
- Merged the three evaluation test modules into
  `evaluation/test_evaluation.py`.
- Kept the offline and operational evaluators separate; they answer different
  questions and have different dependencies.
- Stopped writing derived per-class/confusion and per-email
  consistency/length CSV artifacts. The summaries and raw OOF/run CSVs remain.
- Removed the redundant `bootstrap_rate` wrapper and simplified the evaluator
  return values and imports.

## 13. Simpler offline evaluator
- Split `evaluation/offline_f1.py` into small helpers for synthetic loading,
  task evaluation, joint scoring, and artifact writing.
- Shortened the module docstring, CLI setup, report rendering, and summary
  construction without changing the summary or OOF output.
- Removed type annotations from the evaluator to match the `bert/src` style.

## 14. Leaner operational summary
- Trimmed `operational_benchmark_summary.csv` from 57 columns to 20 headline
  metrics. Latency components, memory/size decompositions, token percentiles,
  per-field agreement, and derived energy details are no longer duplicated in
  the summary.
- Kept per-call latency, labels, raw validity, and token counts in
  `operational_benchmark_runs.csv`.
- Simplified the agreement helper to return exact-match booleans only, and
  removed the now-unused bootstrap calls and elapsed-time plumbing.

## 15. Consolidate requirements
- Added a repo-root `requirements.txt` that includes the app/BERT requirements
  plus the evaluation benchmark dependencies (`psutil`, `codecarbon`).
- Removed `evaluation/requirements.txt`; the evaluation docs now install from
  the repo root.
- Added repo-root environment setup to the README.

## 16. Clearer evaluation names
- Renamed `evaluation/offline_f1.py` to `evaluation/offline_quality.py`.
- Renamed `evaluation/operational_benchmark.py` to
  `evaluation/operational_performance.py`.
- Renamed their result artifacts from `offline_f1_*` and
  `operational_benchmark_*` to `offline_quality_*` and
  `operational_performance_*`.
- Updated imports, commands, and documentation to use the new names.
