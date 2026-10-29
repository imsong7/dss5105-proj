"""Compare classical ML models for the DSS5105 email tasks.

This module is the reporting layer over the same evaluation code the
production trainer uses, so both paths always agree on:

* the 80/20 stratified holdout split (``split_train_test``);
* 5x5 repeated stratified CV on the real training emails;
* synthetic rows added to training folds only;
* TF-IDF options, seeds, folds, and model hyperparameters
  (``build_models`` / ``TASK_*`` in ``train_email_ml``).

Model selection is based on the CV columns, never on the 27-email holdout.

Run the comparison with ``python -m experiments compare``.
"""

from __future__ import annotations

import pandas as pd

from train_email_ml import (
    ARTIFACTS_DIR,
    CV_REPEATS,
    REPORTS_DIR,
    build_models,
    evaluate_holdout,
    evaluate_real_cv_with_synthetic,
    load_synthetic_action_data,
    prepare_synthetic,
    read_labeled_data,
    remove_duplicates_and_check_conflicts,
    split_train_test,
)

TASKS = ("email_category", "required_action")


def evaluate_task(
    data: pd.DataFrame,
    task_name: str,
    synthetic_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Evaluate every comparison model with the production CV protocol."""
    models = build_models(task_name, include_baselines=True)
    train_data, _ = split_train_test(data)
    cv = evaluate_real_cv_with_synthetic(
        train_data,
        synthetic_data,
        task_name,
        n_repeats=CV_REPEATS,
        models=models,
    )
    holdout = evaluate_holdout(
        data,
        synthetic_data,
        task_name,
        models=models,
    )

    rows = []
    for model_name, stats in cv.items():
        rows.append(
            {
                "model": model_name,
                "cv_repeats": int(stats["repeats"]),
                "cv_folds": int(stats["folds"]),
                "cv_macro_f1_mean": float(stats["mean"]),
                "cv_macro_f1_std": float(stats["std"]),
                "cv_accuracy_mean": float(stats["accuracy_mean"]),
                "cv_accuracy_std": float(stats["accuracy_std"]),
            }
        )
    return pd.DataFrame(rows).merge(holdout, on="model")


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
        "\nHoldout is the same 20% real-only split the trainer uses, so treat it "
        "as a sanity check only. Do not choose a model from the holdout column."
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
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

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

    category_results = evaluate_task(category_data, "email_category")
    category_results.insert(0, "task", "email_category")
    action_results = evaluate_task(
        action_data, "required_action", synthetic_action
    )
    action_results.insert(0, "task", "required_action")

    results = pd.concat(
        [category_results, action_results], ignore_index=True
    )
    results = results.sort_values(
        ["task", "cv_macro_f1_mean"],
        ascending=[True, False],
    ).reset_index(drop=True)

    csv_path = REPORTS_DIR / "model_comparison.csv"
    results.to_csv(csv_path, index=False, encoding="utf-8-sig")
    results.to_csv(
        ARTIFACTS_DIR / "model_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    markdown = (
        "# Model comparison\n\n"
        f"CV is {CV_REPEATS}x5 repeated stratified CV on the real training "
        "split only; synthetic emails are added only to required_action "
        "training folds. The 20% real-only holdout is a sanity check and "
        "should not be used for model selection. These are the same split, "
        "folds, and model definitions used by `train_email_ml`.\n\n"
        + format_table(
            category_results.sort_values(
                "cv_macro_f1_mean", ascending=False
            ),
            "email_category",
        )
        + "\n"
        + format_table(
            action_results.sort_values(
                "cv_macro_f1_mean", ascending=False
            ),
            "required_action",
        )
    )
    (REPORTS_DIR / "model_comparison.md").write_text(
        markdown, encoding="utf-8"
    )
    (ARTIFACTS_DIR / "model_comparison.md").write_text(
        markdown, encoding="utf-8"
    )

    print_console_table(results)
    print(
        "\nSaved comparison to:\n"
        f"  {REPORTS_DIR / 'model_comparison.md'}\n"
        f"  {REPORTS_DIR / 'model_comparison.csv'}"
    )
