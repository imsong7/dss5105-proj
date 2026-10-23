# Offline evaluation

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
  energy, and invalid-format rate need the separate operational evaluator.
- The CIs quantify uncertainty from the available labelled emails; they do not
  fix label noise or sampling bias in the original mailbox.
- Synthetic rows are filtered against the real data once before CV. They are
  never in a validation fold, but the filter sees all real rows; this is a minor
  transductive step, not label leakage.
- This is not a substitute for a fresh-mailbox benchmark before deployment.
