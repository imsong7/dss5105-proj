# Evaluation

| Script | Purpose |
|--------|---------|
| `offline_quality.py` | BERT classification quality |
| `operational_performance.py` | Llama and BERT latency, resource use, and output stability |

Neither script requires Flask or mailbox access. Llama requires Ollama.

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

## Outputs and tests

Both scripts write summaries, predictions or per-call records, manifests, and text reports to `evaluation/results/`.

Run model-free unit tests:

```bash
.venv/bin/python -m unittest evaluation.test_evaluation -v
```
