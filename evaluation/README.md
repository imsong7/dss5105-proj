# Evaluation

| Script | Purpose |
|--------|---------|
| `offline_quality.py` | BERT classification quality |
| `operational_performance.py` | Llama and BERT latency, resource use, and output stability |
| `compare_models.py` | Shared quality and latency comparison for built-in and adapter-based models |

The evaluation scripts do not require mailbox access or a running Flask server.
Evaluating Llama requires Ollama.

```bash
.venv/bin/pip install -r requirements.txt
```

## Offline quality

Evaluates BERT using 5-fold stratified out-of-fold predictions and 95% bootstrap confidence intervals (seed 42, 2,000 resamples). Encoders remain frozen; logistic heads are refit per fold. Synthetic data is used only in action-head training folds.

```bash
# Default evaluation
.venv/bin/python evaluation/offline_quality.py

# Real-only baseline
.venv/bin/python evaluation/offline_quality.py --no-synthetic
```

### Results

| Dataset | N | Accuracy [95% CI] | Macro-F1 [95% CI] |
|---------|---|-------------------|-------------------|
| Category head¹ | 132 | 0.864 [0.811, 0.917] | 0.844 [0.780, 0.905] |
| Category end-to-end² | 200 | 0.910 [0.875, 0.945] | 0.870 [0.813, 0.919] |
| Action (real+synthetic) | 134 | 0.843 [0.783, 0.903] | 0.795 [0.707, 0.871] |
| Both labels³ | 133 | 0.737 [0.662, 0.812] | — |

1. Excludes emails handled by the Canvas sender rule.
2. Includes the Canvas sender rule and category head.
3. Exact match on both labels; excludes one email with category `__skip__`.

The real-only action baseline achieves macro-F1 0.697 [0.598, 0.788].

These results evaluate BERT, not Llama accuracy. Confidence intervals do not account for label noise or sampling bias. Synthetic-data filtering sees all real rows before cross-validation, but synthetic rows never enter validation folds.

## Operational performance

Benchmarks the deployed classifier interfaces on 30 action-stratified emails, with 5 runs per email and seed 42.

```bash
# Both backends; unload Llama before the cold call
.venv/bin/python evaluation/operational_performance.py --unload-ollama

# Quick BERT-only run
.venv/bin/python evaluation/operational_performance.py \
    --backend bert --limit 10 --runs 1 --no-energy
```

Use `--limit 0` to evaluate all 134 action-usable unique emails.

### Results

CodeCarbon enabled; Ollama unloaded before the Llama cold call.

| Backend | Load ms | Cold ms | Warm p50 ms | Warm p95 ms | Peak MB | Model MB | Energy kWh |
|---------|--------:|--------:|------------:|------------:|--------:|---------:|-----------:|
| Llama 3.1 8B | 1,388 | 4,178 | 3,298 | 5,334 | 5,746 | 4,693 | 0.002199 |
| BERT heads | 3,398 | 411 | 32.9 | 40.8 | 921 | 598 | 0.000032 |

Warm latency excludes the cold call and two warm-up calls. Peak memory includes Ollama processes for Llama.

| Backend | Invalid format | 5-run consistency | Short/full agreement |
|---------|---------------:|------------------:|---------------------:|
| Llama 3.1 8B | 0/180 calls | 1.000 | 0.767 |
| BERT heads | n/a | 1.000 | 0.967 |

Consistency requires identical category and action labels across all five runs. Short/full agreement compares both labels using the first 200 characters versus the complete dataset text, subject to backend truncation: 3,000 characters for Llama and 256 tokens for BERT.

Results depend on hardware, software, and model loading state. Energy is a machine-wide estimate. Output stability does not establish classification accuracy.

## Comparing models on labeled emails

Use `compare_models.py` to run every model against the same reviewed emails.
It accepts the existing `review_id,Subject,From,Preview,category,action` CSV
format. An optional `Body` column supplies full message content; otherwise
classifiers receive the preview. Blank or `__skip__` labels are excluded only
from that task's quality score, not from the other task's score.

```bash
# Both current models, with the same app sender-rule policy
.venv/bin/python evaluation/compare_models.py

# Select models, a locked test split, and a private output directory
.venv/bin/python evaluation/compare_models.py \
    --model llama --model bert \
    --dataset /path/to/labeled_test.csv --split test \
    --out-dir /path/to/private-results
```

Future models can be added without changing the runner. Provide an importable
factory returning an object with `classify(email)` that returns a mapping or
classification object containing `content_category` and `reply_nature`. When
using only adapters, omit `--model`; to compare adapters alongside built-in
models, specify the built-ins explicitly:

```bash
.venv/bin/python evaluation/compare_models.py \
    --model llama --model bert \
    --adapter agent=project.adapters:make_agent
```

The common input is an `Email` with ID, sender, subject, received time, preview,
and body. For an app-level comparison, the sender category rules are applied
to every model by default; use `--rule-policy none` to evaluate model outputs
without those rules. Adapters should not apply their own duplicate rule.

The runner writes per-email predictions, per-task summary metrics, per-class
precision/recall/F1/support, and a manifest. Macro-F1 and accuracy include
stratified bootstrap 95% confidence intervals; the summary also includes
category/action exact match, latency, error rate, and invalid-output rates.
Latency in this quality run is a single observed call per email; use
`operational_performance.py` for repeated/cold/warm resource benchmarking.
Artifacts include email IDs and predictions, so store them in a private local
directory and do not commit real-email results.

For reliable model selection, use a reviewed, representative, held-out test
split that is never used for tuning. Keep development emails separate, remove
duplicates across splits, and ensure each label has enough examples. This
runner does not create labels or repair class imbalance.

## Outputs and tests

Both scripts write summaries, predictions or per-call records, manifests, and text reports to `evaluation/results/`.

Run model-free unit tests:

```bash
.venv/bin/python -m unittest evaluation.test_evaluation -v
.venv/bin/python -m unittest evaluation.test_compare_models -v
```
