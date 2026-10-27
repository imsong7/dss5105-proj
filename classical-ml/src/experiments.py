"""Run ML comparison, tuning, and synthetic-data experiments.

Use one command with one mode: compare, tune, or ablation.
"""

from __future__ import annotations

import argparse
import math

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import ParameterGrid, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from comparison import CV_REPEATS, evaluate_cv, filtered_synthetic
from train_email_ml import (
    BASE_DIR,
    RANDOM_STATE,
    TEST_SIZE,
    BalancedComplementNB,
    load_synthetic_action_data,
    read_labeled_data,
    remove_duplicates_and_check_conflicts,
)

TASK_MODELS = {
    "email_category": [
        "logistic_regression",
        "linear_svm",
        "complement_nb_balanced",
    ],
    "required_action": ["complement_nb_balanced"],
}

TFIDF_GRID = {
    "tfidf__ngram_range": [(1, 1), (1, 2)],
    "tfidf__min_df": [1, 2],
    "tfidf__max_df": [0.90, 0.98],
    "tfidf__sublinear_tf": [True, False],
}

MODEL_GRID = {
    "logistic_regression": {"classifier__C": [0.1, 1.0, 10.0]},
    "linear_svm": {"classifier__C": [0.1, 1.0, 10.0]},
    "complement_nb_balanced": {"classifier__alpha": [0.1, 0.3, 1.0, 3.0]},
}


def make_pipeline(model_name: str) -> Pipeline:
    if model_name == "logistic_regression":
        classifier = LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        )
    elif model_name == "linear_svm":
        classifier = LinearSVC(
            class_weight="balanced",
            random_state=RANDOM_STATE,
            max_iter=5000,
        )
    elif model_name == "complement_nb_balanced":
        classifier = BalancedComplementNB()
    else:
        raise ValueError(f"Unknown model: {model_name}")

    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    max_features=30000,
                    strip_accents="unicode",
                ),
            ),
            ("classifier", classifier),
        ]
    )


def split_like_training(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    number_of_classes = data["label"].nunique()
    test_count = max(number_of_classes, math.ceil(len(data) * TEST_SIZE))
    return train_test_split(
        data,
        test_size=test_count,
        random_state=RANDOM_STATE,
        stratify=data["label"],
    )


def run_tuning() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    category_data, action_data, _ = read_labeled_data()
    category_data = remove_duplicates_and_check_conflicts(
        category_data, "email_category"
    )
    action_data = remove_duplicates_and_check_conflicts(
        action_data, "required_action"
    )
    synthetic_action = filtered_synthetic(
        load_synthetic_action_data(), action_data
    )
    datasets = {
        "email_category": (category_data, None),
        "required_action": (action_data, synthetic_action),
    }

    all_rows: list[dict[str, object]] = []
    best_by_task: dict[str, dict[str, object]] = {}

    for task, model_names in TASK_MODELS.items():
        data, synthetic = datasets[task]
        train_data, test_data = split_like_training(data)

        for model_name in model_names:
            grid = {**TFIDF_GRID, **MODEL_GRID[model_name]}
            for params in ParameterGrid(grid):
                model = make_pipeline(model_name)
                model.set_params(**params)
                cv_result = evaluate_cv(
                    train_data,
                    synthetic,
                    {model_name: model},
                    n_splits=5,
                    n_repeats=CV_REPEATS,
                ).iloc[0]

                row = {
                    "task": task,
                    "model": model_name,
                    **params,
                    "cv_macro_f1_mean": float(
                        cv_result["cv_macro_f1_mean"]
                    ),
                    "cv_macro_f1_std": float(cv_result["cv_macro_f1_std"]),
                    "cv_accuracy_mean": float(
                        cv_result["cv_accuracy_mean"]
                    ),
                    "cv_accuracy_std": float(cv_result["cv_accuracy_std"]),
                }
                all_rows.append(row)

                current_best = best_by_task.get(task)
                if (
                    current_best is None
                    or row["cv_macro_f1_mean"]
                    > current_best["row"]["cv_macro_f1_mean"]
                ):
                    best_by_task[task] = {
                        "row": row,
                        "params": params.copy(),
                        "model": model_name,
                    }

        print(
            f"\n{task}: tried {sum(1 for row in all_rows if row['task'] == task)} "
            "configurations."
        )

    results = pd.DataFrame(all_rows)
    results.to_csv(
        BASE_DIR / "hyperparameter_tuning.csv",
        index=False,
        encoding="utf-8-sig",
    )

    best_rows: list[dict[str, object]] = []
    for task, best in best_by_task.items():
        data, synthetic = datasets[task]
        train_data, test_data = split_like_training(data)

        model = make_pipeline(best["model"])
        model.set_params(**best["params"])

        if synthetic is not None and not synthetic.empty:
            train_text = pd.concat(
                [train_data["text"], synthetic["text"]], ignore_index=True
            )
            train_label = pd.concat(
                [train_data["label"], synthetic["label"]], ignore_index=True
            )
        else:
            train_text = train_data["text"]
            train_label = train_data["label"]

        model.fit(train_text, train_label)
        predictions = model.predict(test_data["text"])
        holdout_macro_f1 = float(
            f1_score(
                test_data["label"],
                predictions,
                average="macro",
                zero_division=0,
            )
        )
        holdout_accuracy = float(
            accuracy_score(test_data["label"], predictions)
        )

        row = dict(best["row"])
        row["holdout_macro_f1"] = holdout_macro_f1
        row["holdout_accuracy"] = holdout_accuracy
        best_rows.append(row)

    best_frame = pd.DataFrame(best_rows)
    best_frame.to_csv(
        BASE_DIR / "hyperparameter_tuning_best.csv",
        index=False,
        encoding="utf-8-sig",
    )

    markdown_lines = [
        "# Hyperparameter tuning",
        "",
        f"Tuning uses {CV_REPEATS}x5 repeated stratified CV on the real "
        "training split only. The holdout is a one-off sanity check for the "
        "best configuration and is not used for selection.",
        "",
    ]

    for task in TASK_MODELS:
        task_results = results[results["task"] == task].sort_values(
            "cv_macro_f1_mean", ascending=False
        )
        markdown_lines.extend(
            [
                f"## {task}",
                "",
                "| Model | ngram | min_df | max_df | sublinear | C/alpha "
                "| CV Macro-F1 | CV Acc |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for _, row in task_results.head(10).iterrows():
            if row["model"] == "complement_nb_balanced":
                c_or_alpha = row["classifier__alpha"]
            else:
                c_or_alpha = row["classifier__C"]
            markdown_lines.append(
                "| {model} | {ngram} | {min_df} | {max_df} | {sublinear} "
                "| {c_or_alpha} | {cv:.3f} ± {cv_std:.3f} | {acc:.3f} |".format(
                    model=row["model"],
                    ngram=row["tfidf__ngram_range"],
                    min_df=row["tfidf__min_df"],
                    max_df=row["tfidf__max_df"],
                    sublinear=row["tfidf__sublinear_tf"],
                    c_or_alpha=c_or_alpha,
                    cv=row["cv_macro_f1_mean"],
                    cv_std=row["cv_macro_f1_std"],
                    acc=row["cv_accuracy_mean"],
                )
            )
        markdown_lines.append("")

    markdown_lines.extend(
        [
            "## Best configuration per task",
            "",
            "| Task | Model | CV Macro-F1 | CV Acc | Holdout Macro-F1 "
            "| Holdout Acc |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for _, row in best_frame.iterrows():
        markdown_lines.append(
            "| {task} | {model} | {cv:.3f} ± {cv_std:.3f} | {acc:.3f} "
            "| {hold:.3f} | {hold_acc:.3f} |".format(
                task=row["task"],
                model=row["model"],
                cv=row["cv_macro_f1_mean"],
                cv_std=row["cv_macro_f1_std"],
                acc=row["cv_accuracy_mean"],
                hold=row["holdout_macro_f1"],
                hold_acc=row["holdout_accuracy"],
            )
        )

    markdown = "\n".join(markdown_lines) + "\n"
    (BASE_DIR / "hyperparameter_tuning.md").write_text(
        markdown, encoding="utf-8"
    )

    print("\n" + "=" * 100)
    print("BEST HYPERPARAMETERS (training-split repeated CV)")
    print("=" * 100)
    for _, row in best_frame.iterrows():
        params = {
            key: value
            for key, value in row.items()
            if key.startswith(("tfidf__", "classifier__"))
            and pd.notna(value)
        }
        print(f"\n{row['task']} | {row['model']}")
        for key, value in params.items():
            print(f"  {key}: {value}")
        print(
            f"  CV Macro-F1: {row['cv_macro_f1_mean']:.3f} "
            f"(+/- {row['cv_macro_f1_std']:.3f}) | "
            f"Holdout Macro-F1: {row['holdout_macro_f1']:.3f}"
        )

    print(
        "\nSaved tuning results to:\n"
        f"  {BASE_DIR / 'hyperparameter_tuning.md'}\n"
        f"  {BASE_DIR / 'hyperparameter_tuning.csv'}\n"
        f"  {BASE_DIR / 'hyperparameter_tuning_best.csv'}"
    )


def run_ablation() -> None:
    from comparison import (
        CV_REPEATS,
        build_models,
        evaluate_cv,
        filtered_synthetic,
    )
    from train_email_ml import (
        BASE_DIR,
        load_synthetic_action_data,
        read_labeled_data,
        remove_duplicates_and_check_conflicts,
    )

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    _, action_data, _ = read_labeled_data()
    action_data = remove_duplicates_and_check_conflicts(
        action_data, "required_action"
    )
    synthetic = filtered_synthetic(load_synthetic_action_data(), action_data)
    available_models = build_models("required_action")
    model_names = ["linear_svm", "complement_nb", "complement_nb_balanced"]
    models = {name: available_models[name] for name in model_names}

    real = evaluate_cv(
        action_data, None, models, n_splits=5, n_repeats=CV_REPEATS
    ).add_prefix("real_")
    augmented = evaluate_cv(
        action_data, synthetic, models, n_splits=5, n_repeats=CV_REPEATS
    ).add_prefix("with_synthetic_")
    result = augmented.merge(real, left_on="with_synthetic_model", right_on="real_model")
    result = result.rename(
        columns={
            "with_synthetic_model": "model",
            "real_cv_macro_f1_mean": "real_only_macro_f1_mean",
            "real_cv_macro_f1_std": "real_only_macro_f1_std",
            "real_cv_accuracy_mean": "real_only_accuracy_mean",
            "real_cv_accuracy_std": "real_only_accuracy_std",
            "with_synthetic_cv_macro_f1_mean": "with_synthetic_macro_f1_mean",
            "with_synthetic_cv_macro_f1_std": "with_synthetic_macro_f1_std",
            "with_synthetic_cv_accuracy_mean": "with_synthetic_accuracy_mean",
            "with_synthetic_cv_accuracy_std": "with_synthetic_accuracy_std",
        }
    )
    result["delta_macro_f1"] = (
        result["with_synthetic_macro_f1_mean"] - result["real_only_macro_f1_mean"]
    )
    result["delta_accuracy"] = (
        result["with_synthetic_accuracy_mean"] - result["real_only_accuracy_mean"]
    )
    result = result.sort_values("delta_macro_f1", ascending=False)
    result.to_csv(BASE_DIR / "ablation_synthetic.csv", index=False)

    lines = [
        "# Synthetic data ablation (required_action)",
        "",
        f"Real emails: {len(action_data)}; synthetic rows: {len(synthetic)}; "
        f"CV: {CV_REPEATS}x5 repeated stratified.",
        "",
        "| Model | Real-only Macro-F1 | + Synthetic Macro-F1 | Delta | "
        "Real-only Acc | + Synthetic Acc |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for _, row in result.iterrows():
        lines.append(
            f"| {row['model']} | {row['real_only_macro_f1_mean']:.3f} "
            f"± {row['real_only_macro_f1_std']:.3f} | "
            f"{row['with_synthetic_macro_f1_mean']:.3f} "
            f"± {row['with_synthetic_macro_f1_std']:.3f} | "
            f"{row['delta_macro_f1']:+.3f} | "
            f"{row['real_only_accuracy_mean']:.3f} | "
            f"{row['with_synthetic_accuracy_mean']:.3f} |"
        )
    report = "\n".join(lines) + "\n"
    (BASE_DIR / "ablation_synthetic.md").write_text(report, encoding="utf-8")
    print(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("compare", "tune", "ablation"),
        help="experiment to run",
    )
    mode = parser.parse_args().mode
    if mode == "compare":
        from comparison import run_comparison

        run_comparison()
    elif mode == "tune":
        run_tuning()
    else:
        run_ablation()


if __name__ == "__main__":
    main()
