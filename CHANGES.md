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
  BERT: warm p50/p95 33.5/41.6 ms, 972 MB peak, 0.000042 kWh, consistency 1.000.
- Updated the README with operational commands and headline results.
