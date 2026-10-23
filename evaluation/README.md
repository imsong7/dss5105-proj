# Evaluation

Two independent evaluators live here:

| Script | Question it answers |
|--------|---------------------|
| `offline_f1.py` | How accurate are the BERT heads on labelled emails? |
| `operational_benchmark.py` | How fast/heavy/consistent are Llama and BERT when actually called? |

Neither script needs the Flask UI. The offline evaluator does not need Ollama;
the operational benchmark uses Ollama for the Llama backend.

Install the optional operational dependencies once (repo-root `.venv`):

```bash
.venv/bin/pip install -r evaluation/requirements.txt
```

# Offline quality: `offline_f1.py`

`offline_f1.py` measures the BERT heads with **out-of-fold (OOF) predictions**
and **95% bootstrap confidence intervals**. It is deliberately separate from the
Flask app: no mailbox, Ollama, or browser is involved.

## Why OOF instead of the old 27-row test split?

The project has only a few hundred labelled emails. A single 20% test split has
~27 rows, so its macro-F1 moves a lot when the seed changes. In 5-fold
stratified OOF evaluation every labelled email is predicted exactly once by a
model that did not train on it. The result uses all labels and is much more
stable than one small split.

## Run

Use the repo-root `.venv` (Python 3.12 with `torch`, `transformers`,
`scikit-learn`, `pandas`).

```bash
# Deployed configuration: category head real-only; action head real+synthetic
.venv/bin/python evaluation/offline_f1.py

# Real-only baseline for both tasks
.venv/bin/python evaluation/offline_f1.py --no-synthetic

# Faster smoke run
.venv/bin/python evaluation/offline_f1.py --folds 2 --bootstrap 200

# One task only, custom output directory
.venv/bin/python evaluation/offline_f1.py --task action --out-dir /tmp/eval
```

Key options:

| Option | Default | Meaning |
|--------|---------|---------|
| `--folds` | `5` | Stratified CV folds. Must be <= the smallest class count. |
| `--bootstrap` | `2000` | Stratified bootstrap resamples for the 95% CIs. |
| `--seed` | `42` | CV split and bootstrap seed. |
| `--encoder-category` | `bge-small-en` | Frozen encoder for the category head. |
| `--encoder-action` | `e5-small-multi` | Frozen encoder for the action head. |
| `--synthetic` | `bert/data/synthetic.csv` | Synthetic rows, added to training folds only. |
| `--synthetic-tasks` | `action` | Which task gets synthetic rows (`action`, `category`, `both`). |
| `--no-synthetic` | off | Evaluate real data only. |

Unit tests for the bootstrap and rule/head merging logic:

```bash
.venv/bin/python -m unittest evaluation.test_offline_f1 -v
```

## What is scored

| Dataset | N | What it means |
|---------|---|---------------|
| `category_model` | 132 | Category head only. Canvas sender-rule rows are excluded because the app routes them deterministically. |
| `category_end_to_end` | 200 | App path: Canvas sender rule first, category head for the rest. |
| `action` | 134 | Action head. |
| `both_labels` | 133 | Exact match on emails scored by both tasks. The action set has 134 rows, but one has category `__skip__`, so only 133 can be scored jointly. |

Inputs match the BERT backend: `Subject: ...` plus the email preview (200
characters in the current app). The encoder is frozen; only the logistic head is
refit for each fold. Synthetic rows are appended to the training folds and never
to the validation fold.

Macro-F1 uses the labels the model is allowed to predict:

- `category_model`: the five non-Canva categories.
- `category_end_to_end`: all six categories, because the rule predicts Canva.
- `action`: all four action labels.

The bootstrap resamples **within each true class**, so small classes such as
`needs_reply` (9 rows) are not accidentally dropped from a replicate.

## Current results (seed 42, 5 folds, 2,000 resamples)

| Dataset | N | Accuracy [95% CI] | Macro-F1 [95% CI] |
|---------|---|-------------------|-------------------|
| `category_model` | 132 | 0.864 [0.811, 0.917] | 0.844 [0.780, 0.905] |
| `category_end_to_end` | 200 | 0.910 [0.875, 0.945] | 0.870 [0.813, 0.919] |
| `action` (real+synthetic) | 134 | 0.843 [0.783, 0.903] | 0.795 [0.707, 0.871] |
| `both_labels` | 133 | 0.737 [0.662, 0.812] | — |

Real-only action baseline (`--no-synthetic`): macro-F1 **0.697** [0.598, 0.788].
Synthetic rows help the action head in OOF evaluation; this is consistent with
the earlier 27-row comparison, though the absolute numbers are not directly
comparable.

These OOF numbers are the ones to quote for model quality. The old 27-row test
split numbers in `bert/README.md` are kept as historical experiment records.

## Outputs

Flat files under `evaluation/results/`:

| File | Contents |
|------|----------|
| `offline_f1_summary.csv` | One row per dataset: N, accuracy, macro-F1, both 95% CIs. |
| `offline_f1_per_class.csv` | Precision, recall, F1, and support per label. |
| `offline_f1_confusion.csv` | Long-form confusion matrix (`true_label`, `pred_label`, `count`). |
| `offline_f1_oof_predictions.csv` | One held-out prediction per email (`review_id` only; no subject/body). |
| `offline_f1_manifest.json` | Arguments, row counts, taxonomy hash, package versions. |
| `offline_f1_report.txt` | Human-readable summary table. |

## Caveats

- This evaluates **BERT only**. Llama quality, latency, memory, token use,
  energy, and invalid-format rate are covered by the operational benchmark
  below.
- The CIs quantify uncertainty from the available labelled emails; they do not
  fix label noise or sampling bias in the original mailbox.
- Synthetic rows are filtered against the real data once before CV. They are
  never in a validation fold, but the filter sees all real rows; this is a minor
  transductive step, not label leakage.
- This is not a substitute for a fresh-mailbox benchmark before deployment.

# Operational benchmark: `operational_benchmark.py`

This script measures the deployed backends, not just model quality. It uses the
same `Email` objects and classifier interfaces as the Flask app, but it does not
start the web server or fetch a mailbox.

## Run

```bash
# Default: 30-email stratified sample, 5 runs/email, both backends
.venv/bin/python evaluation/operational_benchmark.py

# Llama only, with a true cold start
.venv/bin/python evaluation/operational_benchmark.py \
    --backend llama --limit 20 --runs 5 --unload-ollama

# Fast BERT-only smoke run
.venv/bin/python evaluation/operational_benchmark.py \
    --backend bert --limit 10 --runs 1 --no-energy

# All 134 action-usable unique emails (slow for Llama)
.venv/bin/python evaluation/operational_benchmark.py --limit 0 --runs 5
```

Key options:

| Option | Default | Meaning |
|--------|---------|---------|
| `--backend` | `both` | `llama`, `bert`, or both. |
| `--limit` | `30` | Stratified sample size; `0` = all 134 action-usable unique emails. |
| `--runs` | `5` | Calls per email for consistency and latency. |
| `--warmup` | `2` | Warm-up calls excluded from latency/consistency stats. |
| `--short-chars` | `200` | Short-input length for the input-length comparison. |
| `--unload-ollama` | off | Run `ollama stop <model>` before Llama so the cold call includes model load. |
| `--no-energy` | off | Disable CodeCarbon. |
| `--no-memory` | off | Disable psutil RSS sampling. |
| `--country` | `SGP` | CodeCarbon country code. |

## Protocol

- **Sample:** 30 emails stratified by action label, fixed seed 42. The full
  action-usable set is 134 unique emails. The sample keeps the benchmark
  practical for Llama; use `--limit 0` for all 134.
- **Full input:** the email `Preview` field, which is the body text in
  `labels.csv`. The app truncates Llama to 3,000 characters and BERT to 256
  tokens.
- **Short input:** the first 200 characters of `Preview`.
- **Cold:** the first call after classifier construction. With
  `--unload-ollama`, Ollama is stopped first so the cold call includes model
  loading.
- **Warm:** the `--runs` calls per email after the cold call and warm-up calls.
  Latency is client wall-clock time.
- **Peak memory:** sampled every 150 ms. For Llama, the benchmark process RSS and
  all `ollama`/`llama-server` process RSS are reported separately and summed.
- **Model size:** Llama uses the size reported by Ollama `/api/tags`; BERT sums
  the two head directories and the current Hugging Face encoder snapshots.
- **Tokens:** Llama uses Ollama prompt/eval counts (including the system prompt);
  BERT counts tokenizer input tokens for the category and action heads.
- **Energy:** CodeCarbon `OfflineEmissionsTracker` in machine-wide mode, including
  model load and all calls. It may include the Ollama server.
- **Invalid format:** Llama raw JSON is parsed and checked against the taxonomy
  before Pydantic validators can coerce an invalid label to a default. BERT is
  constrained and reported as not applicable.
- **Consistency:** for each email, all 5 runs must produce the same category and
  action. Per-field rates are also reported.
- **Short/full agreement:** the first full run is compared with one short-input
  run for each email.

## Current results

30 emails, 5 runs each, seed 42, CodeCarbon enabled, Ollama unloaded before the
Llama cold call.

| Backend | Load ms | Cold ms | Warm p50 ms | Warm p95 ms | Peak MB | Model MB | Input tokens | Output tokens | Energy kWh | CO2 kg | Invalid | 5-run consistency | Short/full both |
|---------|--------:|--------:|------------:|------------:|--------:|---------:|-------------:|--------------:|-----------:|-------:|--------:|------------------:|----------------:|
| Llama 3.1 8B | 1,388 | 4,178 | 3,298 | 5,334 | 5,746 | 4,693 | 649.5 | 55.2 | 0.002199 | 0.001035 | 0.000 | 1.000 | 0.767 |
| BERT heads | 6,863 | 476 | 33.5 | 41.6 | 972 | 598 | 351.8 | 0.0 | 0.000042 | 0.000020 | n/a | 1.000 | 0.967 |

Breakdown:

| Backend | Category agreement (200 vs full) | Action agreement | Both |
|---------|---------------------------------:|-----------------:|-----:|
| Llama | 0.967 | 0.800 | 0.767 |
| BERT | 1.000 | 0.967 | 0.967 |

The Llama invalid-format rate was **0/180** scored calls; all 5-run label sets
were identical. BERT is deterministic across repeated calls, so its 5-run
consistency is 1.000.

## Outputs

Flat files under `evaluation/results/`:

| File | Contents |
|------|----------|
| `operational_benchmark_summary.csv` | One row per backend: latency, memory, size, tokens, energy, consistency, agreement. |
| `operational_benchmark_runs.csv` | Every call: phase, latency, labels, raw validity, tokens. |
| `operational_benchmark_consistency.csv` | Per-email 5-run label sets and flags. |
| `operational_benchmark_length.csv` | Per-email full-vs-short labels and agreement. |
| `operational_benchmark_manifest.json` | Sample IDs, arguments, versions, input protocol. |
| `operational_benchmark_report.txt` | Human-readable summary table. |

## Caveats

- This is a **30-email sample**, not the full 134-email quality evaluation.
  Latency p95 is based on 150 warm calls; a larger sample will narrow it.
- Llama latency and energy depend heavily on the machine, Ollama version,
  quantization, and whether the model is already loaded. Quote the cold/warm
  protocol with the numbers.
- CodeCarbon reports machine-wide energy; on this macOS host it does not expose
  a separate GPU power sensor. Treat the energy figures as relative estimates,
  not billing-grade measurements.
- Llama token counts include the ~350-token system prompt, so they are not
  directly comparable to BERT head input tokens.
- The dataset provides one `Preview` field, not a separate full MIME body. The
  "full" condition is therefore the full available preview text after the app's
  input limits.
- BERT's 256-token limit means its "full" input is truncated too; the
  short/full comparison still shows whether the first 200 characters change the
  label.
