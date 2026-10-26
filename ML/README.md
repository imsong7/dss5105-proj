# ML — classical text classifiers

This folder contains the classical (non-BERT) email classifiers for the
DSS5105 project. They are lightweight TF-IDF + linear/Naive Bayes baselines
that are fast to train on a laptop and easy to compare against the BERT
models in `../bert/`.

Two independent tasks are trained:

| Task | Labels | Notes |
|------|--------|-------|
| `email_category` | FoS General, Career Enhancement, Medical (UHC), Others/Out of NUS domain, Promotions | Canvas is handled by the sender rule in `email-sorter/` and is excluded from training. |
| `required_action` | Needs a reply, Needs an action, Further review, Reminder | Uses synthetic rows **only in training folds**. |

## Results (current)

Model selection uses 5x5 repeated stratified CV on real training emails only.
The 27-email holdout is a sanity check, not a selection set.

| Task | Selected model | CV Macro-F1 | Holdout Macro-F1 / Accuracy |
|------|----------------|------------:|----------------------------:|
| `email_category` | `linear_svm` (C=10) | **0.906 ± 0.015** | 0.833 / 0.889 |
| `required_action` | `complement_nb_balanced` (alpha=3) + synthetic | **0.688 ± 0.031** | 0.820 / 0.889 |

Full comparisons are in `model_comparison.md`, `hyperparameter_tuning.md`,
and `ablation_synthetic.md`.

### Balancing

No SMOTE or undersampling is used. Class imbalance is handled by:

- `class_weight="balanced"` on Logistic Regression and LinearSVC;
- `BalancedComplementNB`, which applies inverse-frequency sample weights;
- synthetic augmentation for `required_action` (60 / 60 / 60 / 20 rows),
  bringing the combined training counts from 98 / 16 / 11 / 9 to roughly
  98 / 73 / 69 / 67.

Synthetic rows are added only to training folds. Validation and holdout folds
always contain real emails only.

## Files

| File | Purpose |
|------|---------|
| `train_email_ml.py` | Main trainer: loads the workbook, deduplicates, runs repeated CV, selects the best model, writes metrics/confusion matrices/models. |
| `compare_models.py` | Compares 8 models (including a majority baseline) under the same CV protocol. |
| `tune_models.py` | Grid-searches TF-IDF and classifier hyperparameters on the training split. |
| `ablation_synthetic.py` | Measures the effect of synthetic rows for `required_action`. |
| `generate_synthetic_action_data.py` | Regenerates `synthetic_required_action.csv` (seed-fixed). |
| `requirements-ml.txt` | Python dependencies for this folder. |
| `model_comparison.md/.csv` | Model comparison results. |
| `hyperparameter_tuning.md/.csv`, `hyperparameter_tuning_best.csv` | Tuning results and best configuration per task. |
| `ablation_synthetic.md/.csv` | Synthetic-data ablation results. |
| `synthetic_required_action.csv` | Committed synthetic action rows. |

`ml_outputs/` is created at runtime and is **not committed**: it contains
real email text (test predictions, data splits) and large `.joblib` models.

## Data

The trainer expects a workbook at `ML/labels.xlsx`. It is **not committed**
because it contains real, personal email content. Get the latest copy from the
team drive / the teammate who maintains the labels, then place it here:

```bash
cp "/path/to/labels.xlsx" ML/labels.xlsx
```

Expected format (current workbook):

- A worksheet named `labels` (case-insensitive) with one row per email.
- Required columns: `Subject` or `Preview`/`Body`; `category`; `action`.
- Useful columns: `review_id`, `From`, `Received DateTime`, `source_sheets`,
  `category_note`, `action_note`.

The older format (one label per worksheet, sheet names such as
`Amelia - FoS General`) is still supported as a fallback.

## Setup

Python 3.10+ is recommended.

```bash
cd ML
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-ml.txt
```

On macOS, XGBoost needs `libomp` (e.g. `brew install libomp`). If it is
missing, `compare_models.py` skips XGBoost instead of crashing.

## Run

Run from inside `ML/`:

```bash
python train_email_ml.py          # main training + metrics + models
python compare_models.py          # 8-model comparison
python tune_models.py             # hyperparameter search
python ablation_synthetic.py      # synthetic vs real-only
```

Regenerate the synthetic rows only if you change the generator:

```bash
python generate_synthetic_action_data.py
```

`train_email_ml.py` writes to `ML/ml_outputs/`:

- `{task}_metrics.json`, `training_summary.json`
- `{task}_confusion_matrix.csv/.png`
- `{task}_test_predictions.csv`, `{task}_data_split.csv`
- `{task}_model.joblib`
- `canvas_rule_emails.csv`

`compare_models.py`, `tune_models.py`, and `ablation_synthetic.py` also write
their summary `.md/.csv` files to this folder so the results can be committed
without committing personal email text.

## Evaluation notes

- The dataset is small (~132 category rows and ~134 action rows), so the
  27-email holdout has only 2–7 examples per class. Treat holdout macro-F1 as
  a rough sanity check and prefer the CV mean ± std for model selection.
- Hyperparameters were tuned on the training split, but the same CV split is
  also reported in the summary tables. For a stricter estimate, use nested CV
  or collect a fresh external test set.
- The synthetic action rows are template-generated. The ablation shows a large
  gain, but it should be re-validated on newly collected real emails before
  treating `required_action` as production-ready.
- `Others/Out of NUS domain` has low holdout recall (0.25) because it has the
  fewest real examples and no sender/domain metadata features yet.
