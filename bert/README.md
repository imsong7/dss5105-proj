# BERT email classification experiments

This directory contains the BERT-based experiments for the email-sorter project:
- **Frozen encoder + logistic-regression head** (`train.py --mode head`) — recommended for the app; tiny, fast, and robust on the current 202 labelled emails.
- **Full distilbert fine-tune** (`train.py --mode full`) — baseline fine-tune on real data, with optional synthetic-data augmentation.

## Directory structure

```
bert/
  src/                    # Python package
    __init__.py           # public API
    data.py               # data loading, validation, split, synthetic
    model.py              # Encoder, head training, EmbedPredictor
  train.py                # unified CLI (--mode head|full)
  data/                   # data files
    labels.csv            # hand-labelled real emails (202 rows; 132 category model rows, 134 action rows)
    synthetic.csv         # 91 synthetic emails (seed-fixed)
  models/                 # trained app models (flat naming: {task}_{mode})
    action_head/          # frozen encoder head for action
    action_full/          # distilbert fine-tune for action (~512MB)
    category_head/        # frozen encoder head for category
    category_full/        # distilbert fine-tune for category (~512MB)
  results/                # experiment comparison records (flat files)
    compare_head_summary.txt    # head mode comparison results
    compare_head_runs.csv
    compare_full_summary.txt    # full mode comparison results
    compare_full_summary.csv
    compare_full_runs.csv
  make_synthetic.py       # generates bert/data/synthetic.csv
  README.md               # this file
```

---

## Quick start

All training goes through `bert/train.py`. Pick `--mode head` (default, recommended) or `--mode full`.

```bash
# 1) Validate labels
python bert/train.py --review bert/data/labels.csv --check-only

# 2) Train frozen heads for the app (recommended) -> bert/models/{task}_head/
python bert/train.py --review bert/data/labels.csv --mode head --task category
python bert/train.py --review bert/data/labels.csv --mode head --task action \
    --encoder e5-small-multi --synthetic bert/data/synthetic.csv

# 3) Train full DistilBERT fine-tunes -> bert/models/{task}_full/
python bert/train.py --review bert/data/labels.csv --task both --mode full

# 4) Compare encoders (head) or BERT vs TF-IDF (full), no model saved
python bert/train.py --review bert/data/labels.csv --synthetic bert/data/synthetic.csv \
    --mode head --compare-seeds 1,2,3,4,5,6,7,8,9,10
cat bert/results/compare_head_summary.txt

python bert/train.py --review bert/data/labels.csv --synthetic bert/data/synthetic.csv \
    --mode full --compare-seeds 1,2,3,4,5 --task action
cat bert/results/compare_full_summary.txt
```

Use in the app:

The app wraps the models in `email-sorter/app/bert_classifier.py`. For a
standalone script run from the repo root:

```python
import sys
sys.path.insert(0, "bert")
from src.model import EmbedPredictor

action_clf = EmbedPredictor("bert/models/action_head")
category_clf = EmbedPredictor("bert/models/category_head")
label, conf = action_clf.predict(email.subject, email.body)
```

Canvas emails are still handled first by the sender rule in `email-sorter/app/rules.py`.

---

## Which model to use

| Task | Recommended model | OOF macro F1 | Notes |
|------|-------------------|--------------|-------|
| action | `bert/models/action_head` (e5-small-multi + synthetic) | **0.795** [0.707, 0.871] | Real+synthetic; tiny (`head.joblib` only) |
| category | `bert/models/category_head` (bge-small-en, real only) | **0.844** [0.780, 0.905] model-only; **0.870** [0.813, 0.919] end-to-end | Tiny; end-to-end includes the Canvas sender rule |

These are 5-fold out-of-fold estimates from `evaluation/offline_f1.py`, which
scores all labelled emails once with a model that did not train on them. The
real-only action baseline is 0.697 [0.598, 0.788]. The tables below are the
older 27-row held-out-split results, kept as historical experiment records; do
not compare their absolute values directly with the OOF numbers.

Synthetic data helped the frozen **action** head but **hurt** the full distilbert fine-tune action (0.484 → 0.351). Category does not benefit from synthetic data — consistent with the results below.

---

## Train (unified script)

All training goes through `bert/train.py`. Pick `--mode head` (default, recommended) or `--mode full`.

### Encoder choices (head mode only)

| Name | Model | Size | Notes |
|------|-------|------|-------|
| bge-small-en | BAAI/bge-small-en-v1.5 | 33M | English sentence embeddings; default for category |
| e5-small-multi | intfloat/multilingual-e5-small | 118M | Multilingual (Korean/Chinese); default for action |
| distilbert-mean | distilbert-base-uncased (mean pooling) | — | Existing backbone, frozen |

### Sandbox results (temporary labels, 10 seeds, test = real emails only)

| Encoder | action real | action real+syn | category real |
|---------|-------------|-----------------|---------------|
| bge-small-en | 0.547 ± 0.137 | 0.675 ± 0.114 | **0.868 ± 0.056** |
| e5-small-multi | 0.519 ± 0.137 | **0.731 ± 0.055** | 0.829 ± 0.067 |
| distilbert-mean | 0.565 ± 0.146 | 0.587 ± 0.119 | 0.758 ± 0.084 |

> Full distilbert fine-tune (seed 42, 1 run) reached category macro F1 0.658 — worse than the frozen bge head (0.868).

---

## Full distilbert fine-tune details (--mode full)

Fine-tunes `distilbert-base-uncased` on real data; synthetic rows can be added to TRAIN only (val/test stay real).

```bash
# 1) Validate review CSV
python bert/train.py --review bert/data/labels.csv --mode full --check-only

# 2) Train final model(s) -> bert/models/{task}_full/
python bert/train.py --review bert/data/labels.csv --task both --mode full

# 3) With synthetic data (action only by default)
python bert/train.py --review bert/data/labels.csv --task action --mode full \
    --synthetic bert/data/synthetic.csv
cat bert/models/action_full/metrics.json
```

### Results on real data (seed 42)

| Model | Task | Test macro F1 | Notes |
|-------|------|---------------|-------|
| distilbert fine-tune | action | 0.484 | real-only baseline |
| distilbert fine-tune + syn | action | 0.351 | synthetic hurt here |
| distilbert fine-tune | category | 0.860 | real-only |
| frozen bge head | category | 0.865 | slightly better, much smaller |

---

## Synthetic data

`bert/make_synthetic.py` generates `bert/data/synthetic.csv` (91 rows, seed-fixed). Safety guards in `bert/src/data.py`:
- Synthetic rows added to **train split only** (val/test always real)
- Duplicate removal, exact-real-row removal, TF-IDF cosine ≥ 0.8 removal vs real
- Default `--synthetic-tasks action` (use `both` for category)

### Sandbox results (temporary labels, test = real emails only)

| Task | real only | real + synthetic |
|------|-----------|------------------|
| action (TF-IDF) | 0.437 ± 0.121 | 0.709 ± 0.114 |
| action (distilbert) | 0.484 | 0.351 (1 run) |
| category (distilbert) | 0.860 | not beneficial |

> The most reliable improvement is still collecting more real `needs_reply` / `needs_action` / `reminder` emails.

---

## Multiple-seed comparison

```bash
# Head mode: compare encoders (no model saved)
python bert/train.py --review bert/data/labels.csv --synthetic bert/data/synthetic.csv \
    --mode head --compare-seeds 1,2,3,4,5
cat bert/results/compare_head_summary.txt

# Full mode: compare BERT vs TF-IDF (no model saved)
python bert/train.py --review bert/data/labels.csv --synthetic bert/data/synthetic.csv \
    --mode full --compare-seeds 1,2,3,4,5 --task action
cat bert/results/compare_full_summary.txt
```

Outputs: `compare_head_summary.txt` + `compare_head_runs.csv` (head mode) or
`compare_full_summary.txt`, `compare_full_summary.csv`, `compare_full_runs.csv` (full mode) — flat files,
no per-seed subfolders. Model weights are **not** saved for compare runs. `train.py` prints and
`cat`s the summary after a compare run.
