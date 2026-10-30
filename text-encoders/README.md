# Text encoders

Train encoder-based email classifiers for the app's `encoder` and `hybrid`
backends.

## Approach

- Head mode (default): freeze a pretrained encoder and train a
  logistic-regression classification head.
- Full mode: fine-tune DistilBERT as a separate baseline.

Head mode follows this pipeline:

```text
Email text → Frozen encoder → Pooling → Text embedding → Classification head
```

Category and action use separate models. Only the classification head is
trained in head mode; the encoder remains unchanged.

## Models

| Name | Pretrained model | Pooling | Default role |
|---|---|---|---|
| `bge-small-en` | `BAAI/bge-small-en-v1.5` | CLS | Category |
| `e5-small-multi` | `intfloat/multilingual-e5-small` | Mean | Action |
| `distilbert-mean` | `distilbert-base-uncased` | Mean | Comparison |

CLS pooling uses the first token's final representation. Mean pooling
averages token representations, excluding padding. Both produce one vector
for the classifier.

`distilbert-mean` is a frozen-encoder configuration, not the full-mode
DistilBERT fine-tuning experiment.

## Files

| Path | Purpose |
|---|---|
| `train.py` | Training, validation, and comparison commands |
| `src/data.py` | Data preparation, splits, encoder settings, and synthetic checks |
| `src/model.py` | Encoding, pooling, training, and prediction |
| `../data/labels.csv` | Private, team-labelled real emails |
| `../data/synthetic.csv` | Shared 200-row synthetic dataset |
| `models/` | Saved models, manifests, and metrics |
| `results/` | Comparison summaries and run records |

## Training

Run from the repository root using the shared `.venv`.

Training requires `data/labels.csv`. See
[`../classical-ml/README.md`](../classical-ml/README.md) for data preparation.

```bash
# Validate labels
python text-encoders/train.py --check-only

# Train the default category head
python text-encoders/train.py --task category

# Train the default action head with synthetic examples
python text-encoders/train.py \
    --task action \
    --synthetic data/synthetic.csv

# Optional: fine-tune DistilBERT for both tasks
python text-encoders/train.py --mode full --task both
```

`--review` defaults to `data/labels.csv`. Models are saved under
`text-encoders/models/{task}_{head|full}/`.

## Comparison

```bash
# Compare frozen encoders across seeds
python text-encoders/train.py \
    --task action \
    --synthetic data/synthetic.csv \
    --compare-seeds 1,2,3,4,5

# Compare full DistilBERT fine-tuning with TF-IDF
python text-encoders/train.py \
    --mode full \
    --task action \
    --synthetic data/synthetic.csv \
    --compare-seeds 1,2,3,4,5
```

Summaries and run records are written to `text-encoders/results/`.
Comparison runs do not retain deployable model weights.

## Recorded results

### Single 27-email test split

One run per model, from `models/*/metrics.json`:

| Model | Task | Accuracy | Macro-F1 |
|---|---|---:|---:|
| BGE head | Category | 0.889 | 0.865 |
| DistilBERT full | Category | 0.889 | 0.860 |
| E5 head | Action | 0.778 | 0.511 |
| DistilBERT full | Action | 0.815 | 0.675 |

### Action heads: effect of synthetic training data

Two-seed comparison, tested on real emails only.
Macro-F1 is mean ± sample standard deviation.

| Encoder | Real-only Macro-F1 | With synthetic Macro-F1 |
|---|---:|---:|
| BGE-small | 0.542 ± 0.123 | 0.714 ± 0.188 |
| E5-small-multi | 0.601 ± 0.009 | 0.774 ± 0.047 |
| DistilBERT-mean | 0.654 ± 0.093 | 0.690 ± 0.001 |

These tables describe different experiments and should not be compared
directly. The recorded head comparison uses two seeds, while the example
commands above use five.

Results are preliminary because the dataset and number of runs are small.
See [`../MODEL_COMPARISON.md`](../MODEL_COMPARISON.md) for full comparisons
and evaluation details.

## Synthetic data

Synthetic examples are used for training only. Validation and test sets
remain real-only.

The data pipeline removes duplicates, exact matches to real inputs, and
near-duplicates with TF-IDF cosine similarity ≥ 0.8.

The default is `--synthetic-tasks action`. Category augmentation requires
valid category labels and an explicit `category` or `both` setting.

Synthetic examples supplement, but do not replace, more real labelled emails.

## App integration

```bash
python email-sorter/run.py --backend encoder
python email-sorter/run.py --backend hybrid
```

| Backend | Category | Action |
|---|---|---|
| `encoder` | Encoder head | Encoder head |
| `hybrid` | Classical ML | Encoder head |
