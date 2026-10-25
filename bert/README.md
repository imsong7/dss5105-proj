# BERT email classification

This directory trains the BERT backends for the email-sorter app.

- **Head mode** (`--mode head`, default): frozen encoder + logistic-regression head. Recommended: tiny, fast, and strong on the current labels.
- **Full mode** (`--mode full`): DistilBERT fine-tune baseline, with optional synthetic augmentation.

## Files

| Path | Purpose |
|------|---------|
| `train.py` | Unified trainer (`--mode head\|full`) |
| `src/data.py` | Data loading, validation, splits, synthetic checks |
| `src/model.py` | Encoders, head training, `EmbedPredictor` |
| `src/make_synthetic.py` | Generates `data/synthetic.csv` |
| `data/labels.csv` | 202 hand-labelled emails |
| `data/synthetic.csv` | 91 seed-fixed synthetic emails |
| `models/{task}_{head\|full}/` | Trained models |
| `results/compare_*` | Comparison summaries and run records |

## Quick start

All training goes through `bert/train.py`. `--review` defaults to
`bert/data/labels.csv`; outputs go to `bert/models` and `bert/results`.
Default head encoders: category=`bge-small-en`, action=`e5-small-multi`.

```bash
# Validate labels
python bert/train.py --check-only

# Frozen heads for the app (recommended)
python bert/train.py --task category
python bert/train.py --task action --synthetic bert/data/synthetic.csv

# Optional DistilBERT fine-tune
python bert/train.py --mode full --task both

# Compare head encoders (no model saved)
python bert/train.py --synthetic bert/data/synthetic.csv \
    --compare-seeds 1,2,3,4,5
cat bert/results/compare_head_summary.txt

# Compare full fine-tune vs TF-IDF (no model saved)
python bert/train.py --synthetic bert/data/synthetic.csv \
    --mode full --task action --compare-seeds 1,2,3,4,5
cat bert/results/compare_full_summary.txt
```

The app wraps the models in `email-sorter/app/bert_classifier.py`. Canvas emails are still handled first by the sender rule in `email-sorter/app/rules.py`.

## Model recommendation

| Task | Model | OOF macro-F1 (95% CI) | Notes |
|------|-------|-----------------------|-------|
| action | `bert/models/action_head` (e5-small-multi + synthetic) | **0.795** [0.707, 0.871] | Real+synthetic; tiny (`head.joblib` only) |
| category | `bert/models/category_head` (bge-small-en, real only) | **0.844** [0.780, 0.905] model-only; **0.870** [0.813, 0.919] end-to-end | Tiny; end-to-end includes the Canvas sender rule |

These are 5-fold out-of-fold estimates from `evaluation/offline_quality.py`. The older 27-row split results are historical and not directly comparable.

## Head encoders

| Name | Model | Size | Notes |
|------|-------|------|-------|
| bge-small-en | BAAI/bge-small-en-v1.5 | 33M | English sentence embeddings; default for category |
| e5-small-multi | intfloat/multilingual-e5-small | 118M | Multilingual (Korean/Chinese); default for action |
| distilbert-mean | distilbert-base-uncased (mean pooling) | — | Existing backbone, frozen |

Earlier 10-seed comparisons are in `bert/results/compare_head_*`.

## Full fine-tune

`--mode full` fine-tunes `distilbert-base-uncased` on real data. Synthetic rows can be added to the training split only; validation and test rows stay real.

On the older real-only split (seed 42): action 0.484, category 0.860. Adding synthetic data hurt full action (0.351). The frozen category head was slightly better at 0.865.

## Synthetic data

`python bert/src/make_synthetic.py` regenerates `bert/data/synthetic.csv` (91 rows, seed-fixed). Guards in `bert/src/data.py`:

- synthetic rows go to the training split only;
- duplicates and exact real rows are removed;
- near-duplicates with TF-IDF cosine ≥ 0.8 are removed;
- default `--synthetic-tasks action`; use `both` for category.

Synthetic data helped the frozen action head but hurt the full action fine-tune. More real `needs_reply` / `needs_action` / `reminder` emails remain the most reliable improvement.
