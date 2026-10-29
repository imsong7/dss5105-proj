"""Compare classical ML models for the DSS5105 email tasks.

Evaluation protocol
-------------------
* email_category: 5x5 repeated stratified CV on the real emails only.
* required_action: 5x5 repeated stratified CV on the real emails; synthetic
  rows are added to each training fold only, never to the validation fold.
* A separate 80/20 real-only holdout is also reported as a sanity check.  Model
  selection should be based on the CV columns, not on the 27-email holdout.

Run the comparison with `python -m experiments compare`.
"""

from __future__ import annotations

import ctypes
import math
from pathlib import Path

import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.naive_bayes import ComplementNB, MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import LinearSVC

# macOS XGBoost wheels need libomp.  Preload it when a local copy exists so the
# comparison also runs on this machine without Homebrew.
for _libomp in (
    "/opt/anaconda3/lib/libomp.dylib",
    "/opt/homebrew/opt/libomp/lib/libomp.dylib",
    "/usr/local/opt/libomp/lib/libomp.dylib",
):
    if Path(_libomp).exists():
        try:
            ctypes.CDLL(_libomp, mode=ctypes.RTLD_GLOBAL)
        except OSError:
            pass
        break

try:
    from xgboost import XGBClassifier
except Exception as _xgboost_error:  # libomp missing on some macOS installs
    XGBClassifier = None
    print(f"XGBoost is unavailable and will be skipped: {_xgboost_error}")

from train_email_ml import (
    DEFAULT_TFIDF_OPTIONS,
    OUTPUT_DIR,
    RANDOM_STATE,
    REPORTS_DIR,
    TASK_MODEL_PARAMS,
    TASK_TFIDF_OPTIONS,
    TEST_SIZE,
    BalancedComplementNB,
    load_synthetic_action_data,
    normalise,
    read_workbook,
    remove_duplicates_and_check_conflicts,
)

CV_REPEATS = 5


class XGBTextClassifier(BaseEstimator, ClassifierMixin):
    """XGBoost wrapper that encodes string labels for the sklearn API."""

    def __init__(
        self,
        n_estimators: int = 300,
        max_depth: int = 4,
        learning_rate: float = 0.1,
        subsample: float = 0.9,
        colsample_bytree: float = 0.9,
        random_state: int = RANDOM_STATE,
        n_jobs: int = -1,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.random_state = random_state
        self.n_jobs = n_jobs

    def fit(self, X, y):
        self.encoder_ = LabelEncoder().fit(y)
        self.model_ = XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            random_state=self.random_state,
            n_jobs=self.n_jobs,
            eval_metric="mlogloss",
            tree_method="hist",
        )
        self.model_.fit(X, self.encoder_.transform(y))
        self.classes_ = self.encoder_.classes_
        return self

    def predict(self, X):
        encoded = self.model_.predict(X)
        return self.encoder_.inverse_transform(encoded.astype(int))


def build_models(task_name: str | None = None) -> dict[str, object]:
    tfidf_options = TASK_TFIDF_OPTIONS.get(task_name, DEFAULT_TFIDF_OPTIONS)
    model_params = TASK_MODEL_PARAMS.get(task_name, {})

    def text_pipeline(classifier):
        return Pipeline(
            [
                ("tfidf", TfidfVectorizer(**tfidf_options)),
                ("classifier", classifier),
            ]
        )

    models = {
        "majority_baseline": DummyClassifier(strategy="most_frequent"),
        "logistic_regression": text_pipeline(
            LogisticRegression(
                max_iter=2000,
                class_weight="balanced",
                random_state=RANDOM_STATE,
                **model_params.get("logistic_regression", {}),
            )
        ),
        "linear_svm": text_pipeline(
            LinearSVC(
                class_weight="balanced",
                random_state=RANDOM_STATE,
                **model_params.get("linear_svm", {}),
            )
        ),
        "multinomial_nb": text_pipeline(MultinomialNB()),
        "complement_nb": text_pipeline(ComplementNB()),
        "complement_nb_balanced": text_pipeline(
            BalancedComplementNB(
                **model_params.get("complement_nb_balanced", {})
            )
        ),
        "random_forest": text_pipeline(
            RandomForestClassifier(
                n_estimators=400,
                class_weight="balanced_subsample",
                random_state=RANDOM_STATE,
                n_jobs=-1,
            )
        ),
    }
    if XGBClassifier is not None:
        models["xgboost"] = text_pipeline(XGBTextClassifier())
    return models


def filtered_synthetic(
    synthetic_data: pd.DataFrame,
    real_data: pd.DataFrame,
) -> pd.DataFrame:
    if synthetic_data.empty:
        return synthetic_data
    real_keys = set(real_data["text"].map(normalise))
    filtered = synthetic_data[
        ~synthetic_data["text"].map(normalise).isin(real_keys)
    ].copy()
    filtered["dedupe_key"] = filtered["text"].map(normalise)
    return filtered.drop_duplicates("dedupe_key").reset_index(drop=True)


def evaluate_cv(
    data: pd.DataFrame,
    synthetic_data: pd.DataFrame | None,
    models: dict[str, object],
    n_splits: int = 5,
    n_repeats: int = 1,
) -> pd.DataFrame:
    class_counts = data["label"].value_counts()
    folds = min(n_splits, int(class_counts.min()))
    scores: dict[str, dict[str, list[float]]] = {
        name: {"macro_f1": [], "accuracy": [], "weighted_f1": []}
        for name in models
    }

    for repeat in range(n_repeats):
        cv = StratifiedKFold(
            n_splits=folds,
            shuffle=True,
            random_state=RANDOM_STATE + repeat,
        )
        repeat_scores: dict[str, dict[str, list[float]]] = {
            name: {"macro_f1": [], "accuracy": [], "weighted_f1": []}
            for name in models
        }

        for train_index, validation_index in cv.split(data["text"], data["label"]):
            real_train = data.iloc[train_index]
            real_validation = data.iloc[validation_index]

            if synthetic_data is not None and not synthetic_data.empty:
                validation_keys = set(real_validation["text"].map(normalise))
                extra = synthetic_data[
                    ~synthetic_data["text"].map(normalise).isin(validation_keys)
                ]
                train_text = pd.concat(
                    [real_train["text"], extra["text"]], ignore_index=True
                )
                train_label = pd.concat(
                    [real_train["label"], extra["label"]], ignore_index=True
                )
            else:
                train_text = real_train["text"]
                train_label = real_train["label"]

            for name, model in models.items():
                fitted = clone(model)
                fitted.fit(train_text, train_label)
                predictions = fitted.predict(real_validation["text"])
                repeat_scores[name]["macro_f1"].append(
                    float(
                        f1_score(
                            real_validation["label"],
                            predictions,
                            average="macro",
                            zero_division=0,
                        )
                    )
                )
                repeat_scores[name]["accuracy"].append(
                    float(accuracy_score(real_validation["label"], predictions))
                )
                repeat_scores[name]["weighted_f1"].append(
                    float(
                        f1_score(
                            real_validation["label"],
                            predictions,
                            average="weighted",
                            zero_division=0,
                        )
                    )
                )

        for name in models:
            for metric in ("macro_f1", "accuracy", "weighted_f1"):
                scores[name][metric].append(
                    float(pd.Series(repeat_scores[name][metric]).mean())
                )

    def spread(values: list[float]) -> float:
        return float(pd.Series(values).std()) if len(values) > 1 else 0.0

    rows = []
    for name, values in scores.items():
        rows.append(
            {
                "model": name,
                "cv_repeats": n_repeats,
                "cv_folds": folds,
                "cv_macro_f1_mean": float(pd.Series(values["macro_f1"]).mean()),
                "cv_macro_f1_std": spread(values["macro_f1"]),
                "cv_accuracy_mean": float(pd.Series(values["accuracy"]).mean()),
                "cv_accuracy_std": spread(values["accuracy"]),
                "cv_weighted_f1_mean": float(
                    pd.Series(values["weighted_f1"]).mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def evaluate_holdout(
    data: pd.DataFrame,
    synthetic_data: pd.DataFrame | None,
    models: dict[str, object],
) -> pd.DataFrame:
    number_of_classes = data["label"].nunique()
    test_count = max(
        number_of_classes,
        math.ceil(len(data) * TEST_SIZE),
    )
    train_data, test_data = train_test_split(
        data,
        test_size=test_count,
        random_state=RANDOM_STATE,
        stratify=data["label"],
    )

    if synthetic_data is not None and not synthetic_data.empty:
        test_keys = set(test_data["text"].map(normalise))
        extra = synthetic_data[
            ~synthetic_data["text"].map(normalise).isin(test_keys)
        ]
        train_text = pd.concat(
            [train_data["text"], extra["text"]], ignore_index=True
        )
        train_label = pd.concat(
            [train_data["label"], extra["label"]], ignore_index=True
        )
    else:
        train_text = train_data["text"]
        train_label = train_data["label"]

    rows = []
    for name, model in models.items():
        fitted = clone(model)
        fitted.fit(train_text, train_label)
        predictions = fitted.predict(test_data["text"])
        rows.append(
            {
                "model": name,
                "holdout_macro_f1": float(
                    f1_score(
                        test_data["label"],
                        predictions,
                        average="macro",
                        zero_division=0,
                    )
                ),
                "holdout_accuracy": float(
                    accuracy_score(test_data["label"], predictions)
                ),
            }
        )
    return pd.DataFrame(rows)


def print_console_table(results: pd.DataFrame) -> None:
    display = pd.DataFrame(
        {
            "Task": results["task"],
            "Model": results["model"],
            "CV Macro-F1": results.apply(
                lambda row: (
                    f"{row['cv_macro_f1_mean']:.3f} "
                    f"± {row['cv_macro_f1_std']:.3f}"
                ),
                axis=1,
            ),
            "CV Acc": results.apply(
                lambda row: (
                    f"{row['cv_accuracy_mean']:.3f} "
                    f"± {row['cv_accuracy_std']:.3f}"
                ),
                axis=1,
            ),
            "Holdout Macro-F1": results["holdout_macro_f1"].map(
                lambda value: f"{value:.3f}"
            ),
            "Holdout Acc": results["holdout_accuracy"].map(
                lambda value: f"{value:.3f}"
            ),
        }
    )
    print("\n" + "=" * 100)
    print("MODEL COMPARISON (CV is the primary metric)")
    print("=" * 100)
    print(display.to_string(index=False))
    print(
        "\nHoldout = 27 real emails, so treat it as a sanity check only. "
        "Do not choose a model from the holdout column."
    )


def format_table(frame: pd.DataFrame, task_name: str) -> str:
    lines = [
        f"### {task_name}",
        "",
        "| Model | CV Macro-F1 | CV Accuracy | Holdout Macro-F1 | Holdout Accuracy |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, row in frame.iterrows():
        lines.append(
            "| {model} | {cv:.3f} ± {cv_std:.3f} | {acc:.3f} ± {acc_std:.3f} "
            "| {hold:.3f} | {hold_acc:.3f} |".format(
                model=row["model"],
                cv=row["cv_macro_f1_mean"],
                cv_std=row["cv_macro_f1_std"],
                acc=row["cv_accuracy_mean"],
                acc_std=row["cv_accuracy_std"],
                hold=row["holdout_macro_f1"],
                hold_acc=row["holdout_accuracy"],
            )
        )
    return "\n".join(lines) + "\n"


def run_comparison() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    category_data, action_data, _ = read_workbook()
    category_data = remove_duplicates_and_check_conflicts(
        category_data, "email_category"
    )
    action_data = remove_duplicates_and_check_conflicts(
        action_data, "required_action"
    )

    synthetic_action = filtered_synthetic(
        load_synthetic_action_data(), action_data
    )
    category_models = build_models("email_category")
    action_models = build_models("required_action")

    category_cv = evaluate_cv(
        category_data, None, category_models, n_repeats=CV_REPEATS
    )
    category_holdout = evaluate_holdout(
        category_data, None, category_models
    )
    category_results = category_cv.merge(category_holdout, on="model")
    category_results.insert(0, "task", "email_category")

    action_cv = evaluate_cv(
        action_data, synthetic_action, action_models, n_repeats=CV_REPEATS
    )
    action_holdout = evaluate_holdout(
        action_data, synthetic_action, action_models
    )
    action_results = action_cv.merge(action_holdout, on="model")
    action_results.insert(0, "task", "required_action")

    results = pd.concat(
        [category_results, action_results], ignore_index=True
    )
    results = results.sort_values(
        ["task", "cv_macro_f1_mean"],
        ascending=[True, False],
    ).reset_index(drop=True)

    csv_path = OUTPUT_DIR / "model_comparison.csv"
    results.to_csv(csv_path, index=False, encoding="utf-8-sig")
    results.to_csv(
        REPORTS_DIR / "model_comparison.csv", index=False, encoding="utf-8-sig"
    )

    category_table = category_results.sort_values(
        "cv_macro_f1_mean", ascending=False
    )
    action_table = action_results.sort_values(
        "cv_macro_f1_mean", ascending=False
    )
    markdown = (
        "# Model comparison\n\n"
        f"CV is {CV_REPEATS}x5 repeated stratified CV on real "
        "emails only; synthetic emails are added only to required_action "
        "training folds. The 27-email holdout is a sanity check and should "
        "not be used for model selection.\n\n"
        + format_table(category_table, "email_category")
        + "\n"
        + format_table(action_table, "required_action")
    )
    (OUTPUT_DIR / "model_comparison.md").write_text(
        markdown, encoding="utf-8"
    )
    (REPORTS_DIR / "model_comparison.md").write_text(
        markdown, encoding="utf-8"
    )

    print_console_table(results)
    print(
        "\nSaved comparison to:\n"
        f"  {REPORTS_DIR / 'model_comparison.md'}\n"
        f"  {REPORTS_DIR / 'model_comparison.csv'}\n"
        f"  {OUTPUT_DIR / 'model_comparison.md'}"
    )
