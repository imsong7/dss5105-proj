# Classical ML — text classifiers

This folder contains the classical (non-BERT) email classifiers for the
DSS5105 project. They are lightweight TF-IDF + linear/Naive Bayes baselines
that are fast to train on a laptop and easy to compare against the encoder
models in `../text-encoders/`.

Two independent tasks are trained:

| Task | Labels | Notes |
|------|--------|-------|
| `email_category` | FoS General, Career Enhancement, Medical (UHC), Others/Out of NUS domain, Promotions | Canvas is handled by the sender rule in `email-sorter/` and is excluded from training. |
| `required_action` | Needs a reply, Needs an action, Further review, Reminder | Uses synthetic rows **only in training folds**. |

## Results (current)

Selected models, from `reports/hyperparameter_tuning.md` and
`reports/model_comparison.md`:

| Task | Selected model | CV macro-F1 | Holdout macro-F1 / accuracy |
|------|----------------|------------:|----------------------------:|
| `email_category` | `linear_svm` (C=10) | **0.906 ± 0.015** | 0.833 / 0.889 |
| `required_action` | `complement_nb_balanced` (alpha=3) + synthetic | **0.688 ± 0.031** | 0.820 / 0.889 |

Model selection uses 5×5 repeated stratified CV on real training emails only.
The committed 27-email holdout is a sanity check, not a selection set; with
2–7 examples per class, read its macro-F1 as a rough signal. Full comparisons
are in `reports/model_comparison.md`, `reports/hyperparameter_tuning.md` and
`reports/ablation_synthetic.md`.

## Balancing

No SMOTE or undersampling is used. Class imbalance is handled by:

- `class_weight="balanced"` on Logistic Regression and LinearSVC;
- `BalancedComplementNB`, which applies inverse-frequency sample weights;
- synthetic augmentation for `required_action` (60 / 60 / 60 / 20 rows),
  bringing the combined training counts from 98 / 16 / 11 / 9 to roughly
  98 / 73 / 69 / 67.

Synthetic rows are added only to training folds. Validation and holdout folds
always contain real emails only.

## Structure

- `src/`: trainer, shared comparison utilities, experiment runner, data tools,
  and evaluation adapter.
- `tests/`: ML unit tests.
- `../data/`: shared labels and synthetic action data for both model families.
- `reports/`: committed aggregate experiment reports.
- `artifacts/`: ignored models and generated evaluation files; includes real
  email text and should not be committed.
- `requirements-ml.txt`: Python dependencies.

## Data

The trainer uses `../data/labels.csv` as the shared dataset. It is **not
committed** because it contains real, personal email content. Convert the
team's workbook with:

```bash
cp "/path/to/labels.xlsx" ../data/labels.xlsx
PYTHONPATH=src python -m data_tools convert-labels
```

The converter writes `../data/labels.csv`; classical ML, text encoders, and evaluation use
this same CSV by default. Keep the workbook as the editable source if that's
your team's workflow, and rerun the converter whenever it changes.

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

Python 3.10+ is recommended.

```bash
cd classical-ml
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-ml.txt
```

On macOS, XGBoost needs `libomp` (e.g. `brew install libomp`). If it is
missing, the comparison skips XGBoost instead of crashing.

## Run

Run from inside `classical-ml/`:

```bash
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

Use the shared offline evaluator from the project root to compare the encoder,
classical ML, Llama and Claude methods:

```bash
.venv/bin/python evaluation/quality.py --model all
```

Encoder and classical ML are scored with 5-fold out-of-fold predictions on the
shared `../data/labels.csv`; Llama and Claude are zero-shot. Synthetic action
rows are added to training folds only. See `../evaluation/README.md` for the
full protocol and limitations.

## Evaluation notes

- The dataset is small (~132 category rows and ~134 action rows), so any
  held-out test subset may have only a few examples per class. Interpret its
  scores cautiously and prefer collecting more independently labeled emails.
- Hyperparameters were tuned on the training split, but the same CV split is
  also reported in the summary tables. For a stricter estimate, use nested CV
  or collect a fresh external test set.
- The synthetic action rows are template-generated. The ablation shows a large
  gain, but it should be re-validated on newly collected real emails before
  treating `required_action` as production-ready.
- `Others/Out of NUS domain` has low holdout recall (0.25) because it has the
  fewest real examples and no sender/domain metadata features yet.
