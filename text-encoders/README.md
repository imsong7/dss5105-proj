# Text encoders

Train the encoder-based email classifiers used by the app's `encoder` and
`hybrid` backends.

- **Head mode (default):** frozen encoder + logistic-regression head. Small and fast.
- **Full mode:** DistilBERT fine-tuning baseline.

The app calls this backend `encoder` because the frozen encoder supplies the
features; the head is only a small classifier on top.

## Files

| Path | Purpose |
|---|---|
| `train.py` | Unified trainer (`--mode head\|full`) |
| `src/data.py` | Data loading, validation, splits, synthetic checks |
| `src/model.py` | Encoders, head training, `EmbedPredictor` |
| `../data/labels.csv` | Shared labelled emails (private, local-only) |
| `../data/synthetic.csv` | Shared 200-row action synthetic dataset |
| `models/{task}_{head\|full}/` | Trained models |
| `results/compare_*` | Comparison summaries and run records |

## Train

Run from the repo root with the shared `.venv`. Training needs the shared
`data/labels.csv`; see [`../classical-ml/README.md`](../classical-ml/README.md)
for how to create it from the team workbook.

```bash
# Validate labels
python text-encoders/train.py --check-only

# Frozen heads for the app (recommended)
python text-encoders/train.py --task category
python text-encoders/train.py --task action --synthetic data/synthetic.csv

# Optional DistilBERT fine-tune
python text-encoders/train.py --mode full --task both

# Compare head encoders (no model saved)
python text-encoders/train.py --synthetic data/synthetic.csv \
    --compare-seeds 1,2,3,4,5
cat text-encoders/results/compare_head_summary.txt

# Compare full fine-tune vs TF-IDF (no model saved)
python text-encoders/train.py --synthetic data/synthetic.csv \
    --mode full --task action --compare-seeds 1,2,3,4,5
cat text-encoders/results/compare_full_summary.txt
```

`--review` defaults to the shared `data/labels.csv`. Models go to
`text-encoders/models`, results to `text-encoders/results`.

## Models

| Name | Model | Size | Default task |
|---|---|---|---|
| `bge-small-en` | BAAI/bge-small-en-v1.5 | 33M | category |
| `e5-small-multi` | intfloat/multilingual-e5-small | 118M | action |
| `distilbert-mean` | distilbert-base-uncased (mean pooling) | — | comparison |

## Scores

Single 27-email test split, one run per model (`models/*/metrics.json`):

| Model | Task | Accuracy | Macro F1 |
|---|---|---:|---:|
| `category_head` (bge-small-en) | category | 0.889 | 0.865 |
| `category_full` (DistilBERT) | category | 0.889 | 0.860 |
| `action_head` (e5-small-multi) | action | 0.778 | 0.511 |
| `action_full` (DistilBERT) | action | 0.815 | 0.675 |

Action head comparison over 2 seeds, real vs real + synthetic:

| Encoder | Real F1 | Real acc | + Synthetic F1 | + Synthetic acc |
|---|---:|---:|---:|---:|
| `bge-small-en` | 0.542 ± 0.123 | 0.741 | 0.714 ± 0.188 | 0.833 |
| `e5-small-multi` | 0.601 ± 0.009 | 0.815 | **0.774 ± 0.047** | **0.870** |
| `distilbert-mean` | **0.654 ± 0.093** | 0.759 | 0.690 ± 0.001 | 0.796 |

Two seeds is a small sample. See [`../MODEL_COMPARISON.md`](../MODEL_COMPARISON.md)
for the full tables.

## Synthetic data

`PYTHONPATH=classical-ml/src python -m data_tools generate-synthetic` regenerates
the shared 200-row action dataset. `src/data.py` ensures:

- synthetic rows enter the training split only;
- duplicates and exact real rows are removed;
- near-duplicates with TF-IDF cosine ≥ 0.8 are removed;
- default `--synthetic-tasks action`; use `both` only for category.

Synthetic data helps the frozen action head; it is not a substitute for more
real `needs_reply`, `needs_action`, and `reminder` examples.

## App integration

The app loads these models through `email-sorter/app/encoder_classifier.py`:

```bash
python email-sorter/run.py --backend encoder   # both tasks from the heads
python email-sorter/run.py --backend hybrid    # ML category + encoder action
```

Canvas emails are handled by the sender rule in `email-sorter/app/sender_rules.py`.
