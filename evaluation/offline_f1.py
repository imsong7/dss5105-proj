"""Offline macro-F1 evaluation with out-of-fold predictions and bootstrap CIs.

This evaluates the frozen-encoder heads used by the app. Every email gets
exactly one prediction from stratified K-fold cross-validation, so the score
uses all labelled emails without training and evaluating on the same rows.

Reported sets
-------------
- ``category_model``: category head only. Canvas rows are excluded because the
  app handles them with a deterministic sender rule; 132 rows.
- ``category_end_to_end``: the app path, i.e. sender rule + category head; 200
  unique rows.
- ``action``: action head; 134 rows.
- ``both_labels``: exact-match rate on the 133 unique emails that have both
  labels. The action set has 134 rows, but one has category ``__skip__``.

CIs use a stratified bootstrap over emails (resampling within each true class)
so rare classes are not silently dropped from a replicate.

Usage (repo root, root .venv activated)::

    python evaluation/offline_f1.py
    python evaluation/offline_f1.py --folds 5 --bootstrap 2000
    python evaluation/offline_f1.py --no-synthetic
    python evaluation/offline_f1.py --task action --out-dir /tmp/eval
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
BERT_DIR = REPO_ROOT / "bert"
if str(BERT_DIR) not in sys.path:
    sys.path.insert(0, str(BERT_DIR))

from src.data import (  # noqa: E402
    ENCODERS,
    SKIP,
    build_text,
    load_taxonomy,
    sender_rule_label,
    synthetic_dataset,
    task_dataset,
)
from src.model import FrozenEncoder, fit_head  # noqa: E402

DEFAULT_REVIEW = BERT_DIR / "data" / "labels.csv"
DEFAULT_SYNTHETIC = BERT_DIR / "data" / "synthetic.csv"
DEFAULT_OUT = REPO_ROOT / "evaluation" / "results"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--review", default=str(DEFAULT_REVIEW), help="review CSV")
    ap.add_argument("--task", choices=["both", "category", "action"], default="both")
    ap.add_argument("--folds", type=int, default=5, help="stratified CV folds (default: 5)")
    ap.add_argument(
        "--bootstrap",
        type=int,
        default=2000,
        help="stratified bootstrap resamples for 95%% CIs (default: 2000)",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--encoder-category",
        choices=list(ENCODERS),
        default="bge-small-en",
        help="frozen encoder for the category head",
    )
    ap.add_argument(
        "--encoder-action",
        choices=list(ENCODERS),
        default="e5-small-multi",
        help="frozen encoder for the action head",
    )
    ap.add_argument(
        "--synthetic",
        default=str(DEFAULT_SYNTHETIC),
        help="synthetic CSV added to TRAIN folds only (default: bert/data/synthetic.csv)",
    )
    ap.add_argument(
        "--synthetic-tasks",
        choices=["action", "category", "both"],
        default="action",
        help="which tasks use synthetic rows (default: action, matching the deployed head)",
    )
    ap.add_argument("--no-synthetic", action="store_true", help="evaluate real data only")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--allow-missing-labels", action="store_true")
    return ap.parse_args()


# --------------------------------------------------------------------------- #
# Out-of-fold predictions
# --------------------------------------------------------------------------- #
def oof_for_task(
    task: str,
    df: pd.DataFrame,
    encoder_name: str,
    syn: pd.DataFrame | None,
    folds: int,
    seed: int,
) -> pd.DataFrame:
    """Return one held-out prediction per row using stratified K-fold CV."""
    from sklearn.model_selection import StratifiedKFold

    df = df.reset_index(drop=True)
    if df["label_key"].value_counts().min() < folds:
        counts = df["label_key"].value_counts().to_dict()
        raise SystemExit(
            f"[{task}] cannot make {folds} stratified folds; class counts: {counts}. "
            "Use --folds with a smaller value."
        )

    enc = FrozenEncoder(encoder_name)
    X = enc.encode(list(df["text"]))
    Xs = None
    if syn is not None and len(syn):
        Xs = enc.encode(list(syn["text"]))

    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    rows: list[dict] = []
    for fold, (tr_idx, te_idx) in enumerate(skf.split(df, df["label_key"]), 1):
        Xtr = X[tr_idx]
        ytr = list(df.loc[tr_idx, "label_key"])
        if Xs is not None:
            Xtr = np.vstack([Xtr, Xs])
            ytr = ytr + list(syn["label_key"])

        clf = fit_head(Xtr, ytr)
        probs = clf.predict_proba(X[te_idx])
        pred = clf.classes_[probs.argmax(1)]
        conf = probs.max(1)

        for row_i, label, confidence in zip(te_idx, pred, conf):
            row = df.loc[row_i]
            rows.append(
                {
                    "dataset": task,
                    "task": task,
                    "review_id": row["review_id"],
                    "true_label": row["label_key"],
                    "pred_label": str(label),
                    "confidence": float(confidence),
                    "source": "model",
                    "fold": fold,
                }
            )

    out = pd.DataFrame(rows)
    if len(out) != len(df):
        raise SystemExit(f"[{task}] OOF row count {len(out)} != dataset rows {len(df)}")
    if out["review_id"].duplicated().any():
        raise SystemExit(f"[{task}] duplicate review_id in OOF predictions")
    return out


def category_end_to_end(
    review: pd.DataFrame, oof: pd.DataFrame, expected_labels: list[str]
) -> pd.DataFrame:
    """Combine the Canvas sender rule with category-head OOF predictions."""
    vals = review["category"].fillna("").astype(str).map(str.strip)
    valid = vals.ne("") & vals.ne(SKIP)
    raw = review[valid].copy()
    raw["text"] = [
        build_text(subject, sender, preview)
        for subject, sender, preview in zip(raw["Subject"], raw["From"], raw["Preview"])
    ]
    raw = raw.drop_duplicates("text").reset_index(drop=True)

    model = oof.set_index("review_id")
    rows: list[dict] = []
    missing: list[str] = []
    for _, row in raw.iterrows():
        rule_label = sender_rule_label(row["From"], "category")
        if rule_label:
            pred_label, confidence, source, fold = rule_label, 1.0, "rule", None
        else:
            rid = row["review_id"]
            if rid not in model.index:
                missing.append(rid)
                continue
            m = model.loc[rid]
            pred_label = m["pred_label"]
            confidence = float(m["confidence"])
            source = "model"
            fold = int(m["fold"])

        rows.append(
            {
                "dataset": "category_end_to_end",
                "task": "category",
                "review_id": row["review_id"],
                "true_label": str(row["category"]).strip(),
                "pred_label": pred_label,
                "confidence": confidence,
                "source": source,
                "fold": fold,
            }
        )

    if missing:
        raise SystemExit(
            f"[category] {len(missing)} non-rule rows have no OOF prediction; "
            f"first ids: {missing[:5]}"
        )
    out = pd.DataFrame(rows)
    bad = sorted(set(out["pred_label"]) - set(expected_labels))
    if bad:
        raise SystemExit(f"[category] predictions outside taxonomy: {bad}")
    return out


# --------------------------------------------------------------------------- #
# Metrics and bootstrap
# --------------------------------------------------------------------------- #
def bootstrap_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels: list[str],
    n_boot: int,
    seed: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Stratified bootstrap CIs for accuracy and macro F1."""
    from sklearn.metrics import accuracy_score, f1_score

    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(y_true == c) for c in np.unique(y_true)]
    accs = np.empty(n_boot, dtype=float)
    f1s = np.empty(n_boot, dtype=float)

    for i in range(n_boot):
        idx = np.concatenate(
            [rng.choice(group, size=len(group), replace=True) for group in groups]
        )
        accs[i] = accuracy_score(y_true[idx], y_pred[idx])
        f1s[i] = f1_score(
            y_true[idx], y_pred[idx], labels=labels, average="macro", zero_division=0
        )

    acc_ci = tuple(float(x) for x in np.percentile(accs, [2.5, 97.5]))
    f1_ci = tuple(float(x) for x in np.percentile(f1s, [2.5, 97.5]))
    return acc_ci, f1_ci  # type: ignore[return-value]


def bootstrap_rate(
    correct: np.ndarray, n_boot: int, seed: int
) -> tuple[float, float]:
    """Simple bootstrap CI for a proportion."""
    rng = np.random.default_rng(seed)
    n = len(correct)
    boots = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boots[i] = correct[idx].mean()
    return tuple(float(x) for x in np.percentile(boots, [2.5, 97.5]))  # type: ignore[return-value]


def evaluate_frame(
    name: str,
    task: str,
    frame: pd.DataFrame,
    labels: list[str],
    n_boot: int,
    seed: int,
    notes: str = "",
) -> tuple[dict, list[dict], list[dict]]:
    """Return summary row, per-class rows, and long confusion rows."""
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

    y_true = frame["true_label"].to_numpy()
    y_pred = frame["pred_label"].to_numpy()
    report = classification_report(
        y_true, y_pred, labels=labels, output_dict=True, zero_division=0
    )
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    acc_ci, f1_ci = bootstrap_metrics(y_true, y_pred, labels, n_boot, seed)

    summary = {
        "dataset": name,
        "task": task,
        "n": len(frame),
        "label_count": len(labels),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "accuracy_ci_low": acc_ci[0],
        "accuracy_ci_high": acc_ci[1],
        "macro_f1": float(
            f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
        ),
        "macro_f1_ci_low": f1_ci[0],
        "macro_f1_ci_high": f1_ci[1],
        "bootstrap": n_boot,
        "seed": seed,
        "notes": notes,
    }

    per_class = []
    for label in labels:
        r = report[label]
        per_class.append(
            {
                "dataset": name,
                "task": task,
                "label": label,
                "support": int(r["support"]),
                "precision": float(r["precision"]),
                "recall": float(r["recall"]),
                "f1": float(r["f1-score"]),
            }
        )

    confusion = []
    for i, true_label in enumerate(labels):
        for j, pred_label in enumerate(labels):
            confusion.append(
                {
                    "dataset": name,
                    "task": task,
                    "true_label": true_label,
                    "pred_label": pred_label,
                    "count": int(cm[i, j]),
                }
            )
    return summary, per_class, confusion


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    args = parse_args()
    if args.folds < 2:
        raise SystemExit("--folds must be >= 2")
    if args.bootstrap < 1:
        raise SystemExit("--bootstrap must be >= 1")

    labels, tax_digest = load_taxonomy()
    review = pd.read_csv(args.review, dtype=str, keep_default_na=False)
    tasks = ["category", "action"] if args.task == "both" else [args.task]

    datasets: dict[str, pd.DataFrame] = {}
    infos: dict[str, dict] = {}
    for task in tasks:
        df, info = task_dataset(review, task, labels[task], args.allow_missing_labels)
        datasets[task] = df
        infos[task] = info
        print(
            f"[{task}] rows={info['rows_used']} counts={info['counts']} "
            f"rule_excluded={info['rule_rows_excluded']} "
            f"supported={info['supported_labels']}"
        )

    synthetic_path = None if args.no_synthetic else args.synthetic
    if synthetic_path and not Path(synthetic_path).is_file():
        raise SystemExit(f"Synthetic CSV not found: {synthetic_path} (or pass --no-synthetic)")
    syn_data: dict[str, pd.DataFrame] = {}
    if synthetic_path:
        syn_tasks = (
            ["category", "action"]
            if args.synthetic_tasks == "both"
            else [args.synthetic_tasks]
        )
        for task in tasks:
            if task not in syn_tasks:
                continue
            syn, syn_info = synthetic_dataset(synthetic_path, task, labels[task], datasets[task])
            syn_data[task] = syn
            print(
                f"[{task}] synthetic rows={syn_info['rows']} "
                f"counts={syn_info['counts']} (train folds only)"
            )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    per_class_rows: list[dict] = []
    confusion_rows: list[dict] = []
    oof_frames: list[pd.DataFrame] = []
    eval_frames: dict[str, pd.DataFrame] = {}

    for task in tasks:
        encoder = args.encoder_category if task == "category" else args.encoder_action
        print(f"[{task}] encoding with {encoder} ...", flush=True)
        oof = oof_for_task(
            task,
            datasets[task],
            encoder,
            syn_data.get(task),
            args.folds,
            args.seed,
        )

        if task == "category":
            model_eval = oof.copy()
            model_eval["dataset"] = "category_model"
            eval_frames["category_model"] = model_eval
            oof_frames.append(model_eval)

            model_labels = infos["category"]["supported_labels"]
            row, per_class, confusion = evaluate_frame(
                "category_model",
                "category",
                model_eval,
                model_labels,
                args.bootstrap,
                args.seed,
                "head only; Canvas sender-rule rows excluded",
            )
            summary_rows.append(row)
            per_class_rows.extend(per_class)
            confusion_rows.extend(confusion)

            e2e = category_end_to_end(review, oof, list(labels["category"]))
            eval_frames["category_end_to_end"] = e2e
            oof_frames.append(e2e)
            row, per_class, confusion = evaluate_frame(
                "category_end_to_end",
                "category",
                e2e,
                list(labels["category"]),
                args.bootstrap,
                args.seed,
                "sender rule + head; all category rows",
            )
            summary_rows.append(row)
            per_class_rows.extend(per_class)
            confusion_rows.extend(confusion)
        else:
            action_eval = oof.copy()
            action_eval["dataset"] = "action"
            eval_frames["action"] = action_eval
            oof_frames.append(action_eval)
            row, per_class, confusion = evaluate_frame(
                "action",
                "action",
                action_eval,
                infos["action"]["supported_labels"],
                args.bootstrap,
                args.seed,
                "real+synthetic training folds" if task in syn_data else "real data only",
            )
            summary_rows.append(row)
            per_class_rows.extend(per_class)
            confusion_rows.extend(confusion)

    # Joint metric: both labels correct on emails covered by both evaluations.
    if "category_end_to_end" in eval_frames and "action" in eval_frames:
        cat = eval_frames["category_end_to_end"].set_index("review_id")
        act = eval_frames["action"].set_index("review_id")
        common = sorted(set(cat.index) & set(act.index))
        if not common:
            raise SystemExit("No common review_ids between category and action evaluations")
        cat_ok = (cat.loc[common, "true_label"] == cat.loc[common, "pred_label"]).to_numpy()
        act_ok = (act.loc[common, "true_label"] == act.loc[common, "pred_label"]).to_numpy()
        correct = cat_ok & act_ok
        rate = float(correct.mean())
        ci = bootstrap_rate(correct, args.bootstrap, args.seed)
        summary_rows.append(
            {
                "dataset": "both_labels",
                "task": "both",
                "n": len(common),
                "label_count": None,
                "accuracy": rate,
                "accuracy_ci_low": ci[0],
                "accuracy_ci_high": ci[1],
                "macro_f1": None,
                "macro_f1_ci_low": None,
                "macro_f1_ci_high": None,
                "bootstrap": args.bootstrap,
                "seed": args.seed,
                "notes": "exact match of category and action labels",
            }
        )
        print(
            f"[both_labels] n={len(common)} exact-match={rate:.4f} "
            f"95% CI [{ci[0]:.4f}, {ci[1]:.4f}]"
        )

    # ------------------------------------------------------------------ #
    # Write artifacts
    # ------------------------------------------------------------------ #
    summary = pd.DataFrame(summary_rows)
    if "label_count" in summary.columns:
        summary["label_count"] = summary["label_count"].astype("Int64")
    per_class = pd.DataFrame(per_class_rows)
    confusion = pd.DataFrame(confusion_rows)
    oof_all = pd.concat(oof_frames, ignore_index=True)
    oof_all["fold"] = oof_all["fold"].astype("Int64")
    oof_all = oof_all.sort_values(["task", "dataset", "review_id"]).reset_index(drop=True)

    summary.to_csv(out_dir / "offline_f1_summary.csv", index=False, encoding="utf-8-sig")
    per_class.to_csv(out_dir / "offline_f1_per_class.csv", index=False, encoding="utf-8-sig")
    confusion.to_csv(out_dir / "offline_f1_confusion.csv", index=False, encoding="utf-8-sig")
    oof_all.to_csv(out_dir / "offline_f1_oof_predictions.csv", index=False, encoding="utf-8-sig")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "review_csv": _display_path(args.review),
        "taxonomy_sha256_16": tax_digest,
        "task": args.task,
        "folds": args.folds,
        "bootstrap": args.bootstrap,
        "bootstrap_method": "stratified by true label (percentile CI)",
        "seed": args.seed,
        "encoders": {
            "category": args.encoder_category,
            "action": args.encoder_action,
        },
        "synthetic": (
            _display_path(synthetic_path) if syn_data else None
        ),
        "synthetic_tasks": ",".join(sorted(syn_data)) if syn_data else None,
        "rows": {task: len(datasets[task]) for task in tasks},
        "evaluation_rows": {
            row["dataset"]: int(row["n"]) for row in summary_rows
        },
        "versions": {
            pkg: _version(pkg)
            for pkg in ("numpy", "pandas", "scikit-learn", "torch", "transformers")
        },
    }
    with open(out_dir / "offline_f1_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    report = render_report(summary, manifest)
    (out_dir / "offline_f1_report.txt").write_text(report, encoding="utf-8")
    print("\n" + "=" * 78)
    print(report)
    print("=" * 78)
    print(f"Saved artifacts -> {out_dir}")


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _display_path(path: str) -> str:
    """Prefer a repo-relative path in committed artifacts."""
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def render_report(summary: pd.DataFrame, manifest: dict) -> str:
    lines = [
        "Offline macro-F1 — out-of-fold predictions",
        f"Review CSV: {manifest['review_csv']}",
        f"Folds: {manifest['folds']} (stratified) | Bootstrap: {manifest['bootstrap']} "
        f"({manifest['bootstrap_method']}) | Seed: {manifest['seed']}",
        f"Encoders: category={manifest['encoders']['category']}, "
        f"action={manifest['encoders']['action']}",
        f"Synthetic: {manifest['synthetic'] or 'none'}"
        + (
            f" (tasks: {manifest['synthetic_tasks']})"
            if manifest["synthetic"]
            else ""
        ),
        "",
    ]
    lines.append(f"{'Dataset':<24} {'N':>4}  {'Accuracy [95% CI]':<26} {'Macro F1 [95% CI]':<26}")
    lines.append("-" * 84)
    for _, row in summary.iterrows():
        acc = f"{row['accuracy']:.3f} [{row['accuracy_ci_low']:.3f}, {row['accuracy_ci_high']:.3f}]"
        if pd.isna(row["macro_f1"]):
            f1 = "—"
        else:
            f1 = (
                f"{row['macro_f1']:.3f} "
                f"[{row['macro_f1_ci_low']:.3f}, {row['macro_f1_ci_high']:.3f}]"
            )
        lines.append(f"{row['dataset']:<24} {int(row['n']):>4}  {acc:<26} {f1:<26}")
    both = summary.loc[summary["dataset"] == "both_labels", "n"]
    both_n = int(both.iloc[0]) if len(both) else 0
    lines.extend(
        [
            "",
            "Notes:",
            "- category_model excludes the 68 Canvas sender-rule rows from the model;",
            "  category_end_to_end includes them (rule + head).",
            "- action uses the configured training condition (real+synthetic by default).",
            f"- both_labels is the exact-match rate on {both_n} unique emails covered by",
            "  both tasks; action rows without a usable category label are excluded.",
            "- CIs are percentile bootstrap intervals; they quantify uncertainty from the",
            "  labelled emails, not from a single held-out split.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
