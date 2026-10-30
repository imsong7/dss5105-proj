# Evaluation

Two scripts compare the four classification methods on the same labelled
emails:

| Method | Quality (`quality.py`) | Performance (`performance.py`) |
|---|---|---|
| Text encoders | `encoder` | `encoder` |
| Classical ML | `ml` | `ml` |
| Llama | `llm` | `llm` |
| Claude | `claude` | `claude` |

Quality measures category/action accuracy and macro F1. Performance measures
latency, peak memory, token use, invalid output, and run-to-run consistency.

## Data

| File | Purpose |
|---|---|
| `../data/labels.csv` | Shared labelled emails (real data, gitignored) |
| `../data/synthetic.csv` | 200 synthetic action rows |

Create `labels.csv` from the team workbook as described in
[`../classical-ml/README.md`](../classical-ml/README.md). Synthetic rows are
used in training folds only.

## Quality

```bash
# all four methods, both tasks
python evaluation/quality.py --model all

# trained families only; no API calls
python evaluation/quality.py --model both

# Claude only, capped at 50 emails
python evaluation/quality.py --model claude --claude-limit 50

# one task only
python evaluation/quality.py --model all --task action
```

Encoder and ML use 5-fold out-of-fold predictions, or an explicit
`--train-review`/`--test-review` split. Llama and Claude are zero-shot: one
inference call per unique email. Results go to `results/`:

- `quality_summary.csv`
- `quality_predictions.csv`
- `quality_comparison.png`
- `quality_manifest.json`

## Performance

```bash
# all four methods
python evaluation/performance.py --model all

# no paid API calls
python evaluation/performance.py --model encoder ml llm

# cheaper run
python evaluation/performance.py --model all --limit 10 --runs 3 --claude-limit 5
```

Each backend gets a cold call, warm-up calls, measured runs, and a short-input
pass. Results go to `results/`:

- `performance_summary.csv`
- `performance_runs.csv`
- `performance_comparison.png`
- `performance_manifest.json`

## Requirements

- `data/labels.csv` must exist.
- Llama: `ollama pull llama3.1:8b` and a running Ollama server.
- Claude: `ANTHROPIC_API_KEY` in `claude/.env` and the `anthropic` package.
- Claude API calls cost money; use `--claude-limit` for both scripts.

## Notes

- The dataset is small, so treat per-class scores and the 27-email holdout as
  rough signals; prefer the CV mean and confidence intervals.
- Encoder/ML learn from labelled rows; Llama/Claude are zero-shot. This is a
  real difference between the methods, not a bug.
- The synthetic action rows are template-generated. Re-validate the action
  results on newly collected real emails before treating them as production
  quality.
