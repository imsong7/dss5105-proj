# Model evaluation

| Script | Measures |
|--------|----------|
| `offline_quality.py` | BERT classification quality |
| `operational_performance.py` | Llama/BERT latency, resources, and output stability |
| `compare_models.py` | Quality and latency across built-in models and adapters |

No mailbox or Flask server is needed. Llama evaluation requires Ollama.

```bash
.venv/bin/pip install -r requirements.txt
```

## Offline quality

Evaluates BERT with 5-fold stratified out-of-fold predictions and 95%
bootstrap confidence intervals (seed 42, 2,000 resamples). Encoders are frozen;
heads are refit per fold. Synthetic data is used only to train action heads.

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

The real-only action baseline achieves macro-F1 0.697 [0.598, 0.788]. These
results measure BERT, not Llama. Confidence intervals do not account for label
noise or sampling bias. Synthetic rows never enter validation folds.

## Operational performance

Benchmarks deployed classifier interfaces on 30 action-stratified emails,
with 5 runs per email (seed 42).

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

Warm latency excludes the cold call and two warm-ups. Llama peak memory
includes Ollama processes.

| Backend | Invalid format | 5-run consistency | Short/full agreement |
|---------|---------------:|------------------:|---------------------:|
| Llama 3.1 8B | 0/180 calls | 1.000 | 0.767 |
| BERT heads | n/a | 1.000 | 0.967 |

Consistency requires matching both labels across all runs. Short/full
agreement compares predictions on the first 200 characters and full text
(truncated to 3,000 characters for Llama and 256 tokens for BERT). Results vary
by hardware and model state; energy is a machine-wide estimate. Stability does
not measure classification accuracy.

## Comparing models on labeled emails

`compare_models.py` runs each model on the same reviewed emails. It accepts
`review_id,Subject,From,Preview,category,action` CSV files, with an optional
`Body` column. Blank and `__skip__` labels are omitted from that task's score.

```bash
# Both current models, with the same app sender-rule policy
.venv/bin/python evaluation/compare_models.py

# Select models, a locked test split, and a private output directory
.venv/bin/python evaluation/compare_models.py \
    --model llama --model bert \
    --dataset /path/to/labeled_test.csv --split test \
    --out-dir /path/to/private-results
```

Add future models with an importable factory returning an object whose
`classify(email)` method provides `content_category` and `reply_nature`. Omit
`--model` to run adapters alone; specify built-in models to compare them too:

```bash
.venv/bin/python evaluation/compare_models.py \
    --model llama --model bert \
    --adapter agent=project.adapters:make_agent
```

Each model receives the same `Email` fields. Sender-category rules apply to
every model by default; use `--rule-policy none` to disable them. Adapters
should not apply duplicate rules.

Outputs include per-email predictions, task summaries, per-class scores, and a
manifest. Accuracy and macro-F1 include stratified bootstrap 95% confidence
intervals; summaries also report exact match, latency, errors, and invalid
outputs. This runner makes one call per email; use
`operational_performance.py` for repeated and cold/warm benchmarks. Results
contain email IDs and predictions; keep real-email artifacts private.

Use a representative, reviewed test split that is separate from tuning data.
Remove duplicates across splits and include enough examples per label. The
runner does not create labels or address class imbalance.

## Outputs and tests

Results are written under `evaluation/results/`.

Run model-free unit tests:

```bash
.venv/bin/python -m unittest evaluation.test_evaluation -v
.venv/bin/python -m unittest evaluation.test_compare_models -v
```
