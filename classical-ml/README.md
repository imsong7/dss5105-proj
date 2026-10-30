# Classical ML — text classifiers

This folder contains the classical (TF-IDF + linear/Naive Bayes) email
classifiers for the DSS5105 project. They are lightweight baselines that are
fast to train on a laptop and easy to compare against the text-encoder models
in `../text-encoders/`.

Two independent tasks are trained:

| Task | Labels | Notes |
|------|--------|-------|
| `email_category` | FoS General, Career Enhancement, Medical (UHC), Others/Out of NUS domain, Promotions | Canvas is handled by the sender rule in `email-sorter/` and is excluded from training. |
| `required_action` | Needs a reply, Needs an action, Further review, Reminder | Uses synthetic rows **only in training folds**. |

## Evaluation

Model selection uses 5x5 repeated stratified CV on the training partition.
The reserved 20% holdout is used only for a final sanity check. Existing
comparison, tuning, and ablation reports are in `reports/`; rerun experiments
to refresh them after changing data or training code.

### Recorded best configurations

`train_email_ml`, `experiments compare`, `experiments tune`, and
`experiments ablation` now share one protocol: the same 80/20 stratified
holdout, 5x5 repeated stratified CV, TF-IDF options, seeds, and model
definitions. Model selection uses CV on the real training split only.

| Task | Selected model | CV Macro-F1 | CV accuracy | Holdout Macro-F1 / accuracy |
|------|----------------|------------:|------------:|----------------------------:|
| `email_category` | `linear_svm` (`C=10`) | 0.906 ± 0.015 | 0.909 | 0.833 / 0.889 |
| `required_action` | `complement_nb_balanced` (`alpha=3`) + synthetic | 0.688 ± 0.031 | 0.820 | 0.820 / 0.889 |

`xgboost` is part of the candidate set and the tuning grid for completeness,
but it ranks below the linear models on both tasks at this dataset size. The
comparison report also includes non-candidate baselines (`complement_nb`,
`multinomial_nb`, `random_forest`, `majority_baseline`) that are never eligible
for production selection.

See `reports/model_comparison.md`, `reports/hyperparameter_tuning.md`, and
`reports/ablation_synthetic.md` for model comparisons, tuning results, and the
synthetic-data ablation. [`../MODEL_COMPARISON.md`](../MODEL_COMPARISON.md)
collects these with the encoder and end-to-end results.

### Balancing

No SMOTE or undersampling is used. Class imbalance is handled by:

- `class_weight="balanced"` on Logistic Regression and LinearSVC;
- `BalancedComplementNB`, which applies inverse-frequency sample weights;
- synthetic augmentation for `required_action` (60 / 60 / 60 / 20 rows),
  bringing the combined training counts from 98 / 16 / 11 / 9 to roughly
  98 / 73 / 69 / 67.

Synthetic rows are added only to training folds. Validation and holdout folds
always contain real emails only.

## Structure

- `src/`: trainer, shared comparison utilities, experiment runner, and data
  tools.
- `tests/`: ML unit tests.
- `../data/`: shared labels and synthetic action data for both model families.
- `reports/`: committed aggregate experiment reports.
- `artifacts/`: ignored models and generated evaluation files; includes real
  email text and should not be committed.
- `../requirements.txt`: shared Python dependencies for the whole repo.

## Data

The trainer uses `../data/labels.csv` as the shared dataset. It is **not
committed** because it contains real, personal email content. From
`classical-ml/`, convert the team's workbook with:

```bash
cp "/path/to/labels.xlsx" ../data/labels.xlsx
PYTHONPATH=src python -m data_tools convert-labels
```

The converter writes `../data/labels.csv`; classical ML, text encoders, and
evaluation use this same CSV by default. Keep the workbook as the editable
source if that's your team's workflow, and rerun the converter whenever it
changes.

The source workbook must contain a `labels` worksheet with these columns:

- Required: `review_id`, `Subject`, `From`, `Preview`, `category`, and `action`.
- Other columns are retained when converting and are available to both models.

The shared `../data/synthetic.csv` contains the 200 action-only synthetic rows
used by both model families. Convert labels or regenerate synthetic rows with:

```bash
PYTHONPATH=src python -m data_tools convert-labels
PYTHONPATH=src python -m data_tools generate-synthetic
```

## Setup

Python 3.10+ is recommended. From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

On macOS, XGBoost needs `libomp` (e.g. `brew install libomp`). If it is
missing, the comparison skips XGBoost instead of crashing.

## Run

Run from inside `classical-ml/`:

```bash
cd classical-ml
PYTHONPATH=src python -m train_email_ml
PYTHONPATH=src python -m experiments compare
PYTHONPATH=src python -m experiments tune
PYTHONPATH=src python -m experiments ablation
```

Regenerate synthetic rows only if you change the generator:

```bash
PYTHONPATH=src python -m data_tools generate-synthetic
```

The trainer writes generated models and personal-data outputs to `artifacts/`:

- `{task}_metrics.json`, `training_summary.json`
- `{task}_confusion_matrix.csv/.png`
- `{task}_test_predictions.csv`, `{task}_data_split.csv`
- `{task}_model.joblib`
- `canvas_rule_emails.csv`

The comparison mode writes aggregate `.md/.csv` reports to `reports/` and
`artifacts/` (the latter also supplies the trainer's comparison summary).
Tuning and ablation write reports to `reports/`.

## Compare model quality

Use the shared offline evaluator from the project root to compare encoder,
classical ML, and LLM models:

```bash
python evaluation/quality.py --model all
```

For a separate held-out comparison, pass disjoint shared-label files. Fit
encoder and ML models on the training file and use the test file only for
scoring and LLM inference:

```bash
python evaluation/quality.py \
    --model all \
    --train-review /path/to/train.csv \
    --test-review /path/to/test.csv \
    --no-synthetic
```

Use the same subject/preview fields and app category/action label keys in both
files. The evaluator rejects overlapping review IDs and identical task inputs
across the split. Synthetic action rows, if enabled, are added to training
only.

## Evaluation notes

- The dataset is small (~132 category rows and ~134 action rows). The committed
  27-email holdout has only 2–7 examples per class, so treat its macro-F1 as a
  rough sanity check and prefer the CV mean ± std for model selection.
- Hyperparameters were tuned on the training split, but the same CV split is
  also reported in the summary tables. For a stricter estimate, use nested CV
  or collect a fresh external test set.
- The synthetic action rows are template-generated. The ablation shows a large
  gain, but it should be re-validated on newly collected real emails before
  treating `required_action` as production-ready.
- `Others/Out of NUS domain` has low holdout recall (0.25) because it has the
  fewest real examples and no sender/domain metadata features yet.
