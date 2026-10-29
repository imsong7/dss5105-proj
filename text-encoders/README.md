# Text-encoder email classification

Train the email-sorter encoder-based backends here.

- **Head mode** (default): frozen encoder plus logistic-regression head; small and fast.
- **Full mode**: DistilBERT fine-tuning baseline.

## Files

| Path | Purpose |
|------|---------|
| `train.py` | Unified trainer (`--mode head\|full`) |
| `src/data.py` | Data loading, validation, splits, synthetic checks |
| `src/model.py` | Encoders, head training, `EmbedPredictor` |
| `../data/labels.csv` | Shared labeled emails for both model families (private, local-only) |
| `../data/synthetic.csv` | Shared 200-row action synthetic dataset |
| `models/{task}_{head\|full}/` | Trained models |
| `results/compare_*` | Comparison summaries and run records |

## Quick start

Run training from the project root with `text-encoders/train.py`. By default, `--review`
uses the shared `data/labels.csv`; outputs go to `text-encoders/models` and
`text-encoders/results`. Both model families therefore train from the same labeled rows.
The CSV is converted from the private workbook with
`PYTHONPATH=classical-ml/src python -m data_tools convert-labels`.
The default head encoders are `bge-small-en` (category) and `e5-small-multi` (action).

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

The app loads these models through `email-sorter/app/bert_classifier.py`.
The app currently retains `bert` as the backend key for compatibility.
Canvas emails are handled by the sender rule in `email-sorter/app/rules.py`.

## Model recommendation

| Task | Model | OOF macro-F1 (95% CI) | Notes |
|------|-------|-----------------------|-------|
| action | `text-encoders/models/action_head` (e5-small-multi + synthetic) | **0.795** [0.707, 0.871] | Real+synthetic; tiny (`head.joblib` only) |
| category | `text-encoders/models/category_head` (bge-small-en, real only) | **0.844** [0.780, 0.905] model-only; **0.870** [0.813, 0.919] end-to-end | Tiny; end-to-end includes the Canvas sender rule |

Scores are 5-fold out-of-fold estimates from `evaluation/quality.py`.
These are historical runs: the action result used the retired encoder-specific
synthetic set, not the new shared 200-row file. Retrain and reevaluate before
using the score as evidence for the shared synthetic data.

## Head encoders

| Name | Model | Size | Notes |
|------|-------|------|-------|
| bge-small-en | BAAI/bge-small-en-v1.5 | 33M | English sentence embeddings; default for category |
| e5-small-multi | intfloat/multilingual-e5-small | 118M | Multilingual (Korean/Chinese); default for action |
| distilbert-mean | distilbert-base-uncased (mean pooling) | — | Existing backbone, frozen |

Earlier 10-seed comparisons are in `text-encoders/results/compare_head_*`.

## Full fine-tune

`--mode full` fine-tunes `distilbert-base-uncased`. Synthetic rows are added
only to training; validation and test rows remain real. On an older real-only
split (seed 42), full-mode action scored 0.484 and category 0.860; synthetic
data reduced full-mode action to 0.351.

## Synthetic data

`PYTHONPATH=classical-ml/src python -m data_tools generate-synthetic`
regenerates the shared 200-row action dataset. `text-encoders/src/data.py` ensures:

- synthetic rows go to the training split only;
- duplicates and exact real rows are removed;
- near-duplicates with TF-IDF cosine ≥ 0.8 are removed;
- default `--synthetic-tasks action`; use `both` for category.

Synthetic data helped the frozen action head but hurt full-mode action results.
The shared file contains action labels only; use it with the default action
augmentation (`--synthetic-tasks action`), not `--synthetic-tasks both`.
More real `needs_reply`, `needs_action`, and `reminder` examples are preferable.
