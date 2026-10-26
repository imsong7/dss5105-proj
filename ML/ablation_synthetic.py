"""Ablation study: does synthetic data help required_action?

Compares the same model with real-only training vs real+synthetic training,
using the repeated real-email CV protocol from compare_models.py.

Run:
    python ablation_synthetic.py
"""

from __future__ import annotations

import pandas as pd

from compare_models import CV_REPEATS, build_models, evaluate_cv, filtered_synthetic
from train_email_ml import (
    BASE_DIR,
    OUTPUT_DIR,
    load_synthetic_action_data,
    read_workbook,
    remove_duplicates_and_check_conflicts,
)

MODEL_NAMES = ["linear_svm", "complement_nb", "complement_nb_balanced"]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _, action_data, _ = read_workbook()
    action_data = remove_duplicates_and_check_conflicts(
        action_data, "required_action"
    )
    synthetic = filtered_synthetic(
        load_synthetic_action_data(), action_data
    )

    available = build_models("required_action")
    models = {name: available[name] for name in MODEL_NAMES}

    real_only = evaluate_cv(
        action_data,
        None,
        models,
        n_splits=5,
        n_repeats=CV_REPEATS,
    ).rename(
        columns={
            "cv_macro_f1_mean": "real_only_macro_f1_mean",
            "cv_macro_f1_std": "real_only_macro_f1_std",
            "cv_accuracy_mean": "real_only_accuracy_mean",
            "cv_accuracy_std": "real_only_accuracy_std",
        }
    )
    with_synthetic = evaluate_cv(
        action_data,
        synthetic,
        models,
        n_splits=5,
        n_repeats=CV_REPEATS,
    ).rename(
        columns={
            "cv_macro_f1_mean": "with_synthetic_macro_f1_mean",
            "cv_macro_f1_std": "with_synthetic_macro_f1_std",
            "cv_accuracy_mean": "with_synthetic_accuracy_mean",
            "cv_accuracy_std": "with_synthetic_accuracy_std",
        }
    )

    result = with_synthetic[
        [
            "model",
            "with_synthetic_macro_f1_mean",
            "with_synthetic_macro_f1_std",
            "with_synthetic_accuracy_mean",
            "with_synthetic_accuracy_std",
        ]
    ].merge(
        real_only[
            [
                "model",
                "real_only_macro_f1_mean",
                "real_only_macro_f1_std",
                "real_only_accuracy_mean",
                "real_only_accuracy_std",
            ]
        ],
        on="model",
    )
    result["delta_macro_f1"] = (
        result["with_synthetic_macro_f1_mean"]
        - result["real_only_macro_f1_mean"]
    )
    result["delta_accuracy"] = (
        result["with_synthetic_accuracy_mean"]
        - result["real_only_accuracy_mean"]
    )
    result = result.sort_values("delta_macro_f1", ascending=False).reset_index(
        drop=True
    )

    display = pd.DataFrame(
        {
            "Model": result["model"],
            "Real-only Macro-F1": result.apply(
                lambda row: (
                    f"{row['real_only_macro_f1_mean']:.3f} "
                    f"± {row['real_only_macro_f1_std']:.3f}"
                ),
                axis=1,
            ),
            "+ Synthetic Macro-F1": result.apply(
                lambda row: (
                    f"{row['with_synthetic_macro_f1_mean']:.3f} "
                    f"± {row['with_synthetic_macro_f1_std']:.3f}"
                ),
                axis=1,
            ),
            "Delta Macro-F1": result["delta_macro_f1"].map(
                lambda value: f"{value:+.3f}"
            ),
            "+ Synthetic Acc": result.apply(
                lambda row: (
                    f"{row['with_synthetic_accuracy_mean']:.3f} "
                    f"± {row['with_synthetic_accuracy_std']:.3f}"
                ),
                axis=1,
            ),
        }
    )

    print("\n" + "=" * 88)
    print(
        "SYNTHETIC DATA ABLATION (required_action; real-email repeated CV)"
    )
    print("=" * 88)
    print(display.to_string(index=False))
    print(
        f"\nReal emails: {len(action_data)} | synthetic rows: {len(synthetic)} | "
        f"CV: {CV_REPEATS}x5 repeated stratified."
    )

    csv_path = OUTPUT_DIR / "ablation_synthetic.csv"
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    result.to_csv(
        BASE_DIR / "ablation_synthetic.csv", index=False, encoding="utf-8-sig"
    )

    markdown_lines = [
        "# Synthetic data ablation (required_action)",
        "",
        f"Real emails: {len(action_data)}; synthetic rows: {len(synthetic)}; "
        f"CV: {CV_REPEATS}x5 repeated stratified on real emails.",
        "",
        "| Model | Real-only Macro-F1 | + Synthetic Macro-F1 | Delta | "
        "+ Synthetic Accuracy |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, row in result.iterrows():
        markdown_lines.append(
            "| {model} | {real:.3f} ± {real_std:.3f} | {syn:.3f} ± {syn_std:.3f} "
            "| {delta:+.3f} | {acc:.3f} ± {acc_std:.3f} |".format(
                model=row["model"],
                real=row["real_only_macro_f1_mean"],
                real_std=row["real_only_macro_f1_std"],
                syn=row["with_synthetic_macro_f1_mean"],
                syn_std=row["with_synthetic_macro_f1_std"],
                delta=row["delta_macro_f1"],
                acc=row["with_synthetic_accuracy_mean"],
                acc_std=row["with_synthetic_accuracy_std"],
            )
        )
    markdown = "\n".join(markdown_lines) + "\n"
    (OUTPUT_DIR / "ablation_synthetic.md").write_text(
        markdown, encoding="utf-8"
    )
    (BASE_DIR / "ablation_synthetic.md").write_text(markdown, encoding="utf-8")

    print(
        "\nSaved ablation to:\n"
        f"  {BASE_DIR / 'ablation_synthetic.md'}\n"
        f"  {BASE_DIR / 'ablation_synthetic.csv'}"
    )


if __name__ == "__main__":
    main()
