"""Run ML comparison, tuning, and synthetic-data experiments.

Use one command with one mode: compare, tune, or ablation.

All three modes share the production protocol in ``train_email_ml``: the same
80/20 stratified holdout, 5x5 repeated CV, TF-IDF options, and model
definitions. Reports are written to ``classical-ml/reports``.
"""

from __future__ import annotations

import argparse

import pandas as pd
from sklearn.model_selection import ParameterGrid

from train_email_ml import (
    CANDIDATE_MODELS,
    CV_REPEATS,
    REPORTS_DIR,
    build_models,
    evaluate_holdout,
    evaluate_real_cv_with_synthetic,
    load_synthetic_action_data,
    make_pipeline,
    prepare_synthetic,
    read_labeled_data,
    remove_duplicates_and_check_conflicts,
    split_train_test,
)

TASK_MODELS = {
    "email_category": list(CANDIDATE_MODELS),
    "required_action": list(CANDIDATE_MODELS),
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
    "xgboost": {"classifier__max_depth": [3, 5]},
}


def tuning_key_param(model_name: str, row: pd.Series) -> str:
    """Return the human-readable model-specific value for the report table."""
    if model_name == "complement_nb_balanced":
        return f"alpha={row['classifier__alpha']}"
    if model_name == "xgboost":
        return f"depth={row['classifier__max_depth']}"
    return f"C={row['classifier__C']}"


def load_datasets() -> dict[str, tuple[pd.DataFrame, pd.DataFrame | None]]:
    category_data, action_data, _ = read_labeled_data()
    category_data = remove_duplicates_and_check_conflicts(
        category_data, "email_category"
    )
    action_data = remove_duplicates_and_check_conflicts(
        action_data, "required_action"
    )
    synthetic_action = prepare_synthetic(
        load_synthetic_action_data(), action_data
    )
    return {
        "email_category": (category_data, None),
        "required_action": (action_data, synthetic_action),
    }


def run_tuning() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    datasets = load_datasets()

    all_rows: list[dict[str, object]] = []
    best_by_task: dict[str, dict[str, object]] = {}

    for task, model_names in TASK_MODELS.items():
        data, synthetic = datasets[task]
        train_data, _ = split_train_test(data)

        for model_name in model_names:
            grid = {**TFIDF_GRID, **MODEL_GRID[model_name]}
            for params in ParameterGrid(grid):
                model = make_pipeline(model_name)
                model.set_params(**params)
                stats = evaluate_real_cv_with_synthetic(
                    train_data,
                    synthetic,
                    task,
                    n_splits=5,
                    n_repeats=CV_REPEATS,
                    models={model_name: model},
                )[model_name]

                row = {
                    "task": task,
                    "model": model_name,
                    **params,
                    "cv_macro_f1_mean": float(stats["mean"]),
                    "cv_macro_f1_std": float(stats["std"]),
                    "cv_accuracy_mean": float(stats["accuracy_mean"]),
                    "cv_accuracy_std": float(stats["accuracy_std"]),
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
        REPORTS_DIR / "hyperparameter_tuning.csv",
        index=False,
        encoding="utf-8-sig",
    )

    best_rows: list[dict[str, object]] = []
    for task, best in best_by_task.items():
        data, synthetic = datasets[task]

        model = make_pipeline(best["model"])
        model.set_params(**best["params"])
        holdout = evaluate_holdout(
            data,
            synthetic,
            task,
            models={best["model"]: model},
        ).iloc[0]

        row = dict(best["row"])
        row["holdout_macro_f1"] = float(holdout["holdout_macro_f1"])
        row["holdout_accuracy"] = float(holdout["holdout_accuracy"])
        best_rows.append(row)

    best_frame = pd.DataFrame(best_rows)
    best_frame.to_csv(
        REPORTS_DIR / "hyperparameter_tuning_best.csv",
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
                "| Model | ngram | min_df | max_df | sublinear | C/alpha/depth "
                "| CV Macro-F1 | CV Acc |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for _, row in task_results.head(10).iterrows():
            markdown_lines.append(
                "| {model} | {ngram} | {min_df} | {max_df} | {sublinear} "
                "| {key_param} | {cv:.3f} ± {cv_std:.3f} | {acc:.3f} |".format(
                    model=row["model"],
                    ngram=row["tfidf__ngram_range"],
                    min_df=row["tfidf__min_df"],
                    max_df=row["tfidf__max_df"],
                    sublinear=row["tfidf__sublinear_tf"],
                    key_param=tuning_key_param(row["model"], row),
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
    (REPORTS_DIR / "hyperparameter_tuning.md").write_text(
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
        f"  {REPORTS_DIR / 'hyperparameter_tuning.md'}\n"
        f"  {REPORTS_DIR / 'hyperparameter_tuning.csv'}\n"
        f"  {REPORTS_DIR / 'hyperparameter_tuning_best.csv'}"
    )


def run_ablation() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    datasets = load_datasets()
    action_data, synthetic = datasets["required_action"]
    train_data, _ = split_train_test(action_data)

    available_models = build_models("required_action", include_baselines=True)
    model_names = ["linear_svm", "complement_nb", "complement_nb_balanced"]
    models = {name: available_models[name] for name in model_names}

    real = evaluate_real_cv_with_synthetic(
        train_data,
        None,
        "required_action",
        n_repeats=CV_REPEATS,
        models=models,
    )
    augmented = evaluate_real_cv_with_synthetic(
        train_data,
        synthetic,
        "required_action",
        n_repeats=CV_REPEATS,
        models=models,
    )

    rows = []
    for name in model_names:
        rows.append(
            {
                "model": name,
                "real_only_macro_f1_mean": real[name]["mean"],
                "real_only_macro_f1_std": real[name]["std"],
                "with_synthetic_macro_f1_mean": augmented[name]["mean"],
                "with_synthetic_macro_f1_std": augmented[name]["std"],
                "real_only_accuracy_mean": real[name]["accuracy_mean"],
                "with_synthetic_accuracy_mean": augmented[name][
                    "accuracy_mean"
                ],
            }
        )
    result = pd.DataFrame(rows)
    result["delta_macro_f1"] = (
        result["with_synthetic_macro_f1_mean"]
        - result["real_only_macro_f1_mean"]
    )
    result["delta_accuracy"] = (
        result["with_synthetic_accuracy_mean"]
        - result["real_only_accuracy_mean"]
    )
    result = result.sort_values("delta_macro_f1", ascending=False)
    result.to_csv(REPORTS_DIR / "ablation_synthetic.csv", index=False)

    lines = [
        "# Synthetic data ablation (required_action)",
        "",
        f"Real emails: {len(train_data)} (training split); synthetic rows: "
        f"{len(synthetic)}; CV: {CV_REPEATS}x5 repeated stratified.",
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
    (REPORTS_DIR / "ablation_synthetic.md").write_text(
        report, encoding="utf-8"
    )
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
