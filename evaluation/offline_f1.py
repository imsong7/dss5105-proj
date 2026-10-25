"""Offline macro-F1 evaluation with out-of-fold predictions and bootstrap CIs.

Each email is predicted once by a model trained on the other folds, so no row is
scored by its own training data. CIs use a stratified bootstrap over emails.

Usage:
    python evaluation/offline_f1.py
    python evaluation/offline_f1.py --task action --no-synthetic
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
BERT_DIR = REPO_ROOT / "bert"
for _path in (REPO_ROOT, BERT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evaluation import (  # noqa: E402
    bootstrap_proportion,
    display_path,
    package_version,
)
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


def parse_args():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--review", default=str(DEFAULT_REVIEW))
    ap.add_argument("--task", choices=["both", "category", "action"], default="both")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--encoder-category", choices=list(ENCODERS), default="bge-small-en")
    ap.add_argument("--encoder-action", choices=list(ENCODERS), default="e5-small-multi")
    ap.add_argument("--synthetic", default=str(DEFAULT_SYNTHETIC))
    ap.add_argument(
        "--synthetic-tasks", choices=["action", "category", "both"], default="action"
    )
    ap.add_argument("--no-synthetic", action="store_true")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--allow-missing-labels", action="store_true")
    return ap.parse_args()


# --- Out-of-fold predictions ---
def oof_for_task(task, df, encoder_name, syn, folds, seed):
    """Return one held-out prediction per row using stratified K-fold CV."""
    from sklearn.model_selection import StratifiedKFold

    df = df.reset_index(drop=True)
    counts = df["label_key"].value_counts()
    if counts.min() < folds:
        raise SystemExit(
            f"[{task}] cannot make {folds} stratified folds; class counts: "
            f"{counts.to_dict()}. Use --folds with a smaller value."
        )

    enc = FrozenEncoder(encoder_name)
    X = enc.encode(df["text"].tolist())
    Xs = enc.encode(syn["text"].tolist()) if syn is not None and len(syn) else None

    frames = []
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for fold, (tr_idx, te_idx) in enumerate(skf.split(df, df["label_key"]), 1):
        Xtr = X[tr_idx]
        ytr = df["label_key"].iloc[tr_idx].tolist()
        if Xs is not None:
            Xtr = np.vstack([Xtr, Xs])
            ytr += syn["label_key"].tolist()

        clf = fit_head(Xtr, ytr)
        probs = clf.predict_proba(X[te_idx])
        test = (
            df.iloc[te_idx][["review_id", "label_key"]]
            .rename(columns={"label_key": "true_label"})
            .copy()
        )
        test["dataset"] = task
        test["task"] = task
        test["pred_label"] = clf.classes_[probs.argmax(1)].astype(str)
        test["confidence"] = probs.max(1).astype(float)
        test["source"] = "model"
        test["fold"] = fold
        frames.append(
            test[
                [
                    "dataset",
                    "task",
                    "review_id",
                    "true_label",
                    "pred_label",
                    "confidence",
                    "source",
                    "fold",
                ]
            ]
        )

    out = pd.concat(frames, ignore_index=True)
    if len(out) != len(df):
        raise SystemExit(f"[{task}] OOF row count {len(out)} != dataset rows {len(df)}")
    if out["review_id"].duplicated().any():
        raise SystemExit(f"[{task}] duplicate review_id in OOF predictions")
    return out


def category_end_to_end(review, oof, expected_labels):
    """Combine the Canvas sender rule with category-head OOF predictions."""
    vals = review["category"].fillna("").astype(str).str.strip()
    raw = review[vals.ne("") & vals.ne(SKIP)].copy()
    raw["text"] = [
        build_text(subject, sender, preview)
        for subject, sender, preview in zip(raw["Subject"], raw["From"], raw["Preview"])
    ]
    raw = raw.drop_duplicates("text").reset_index(drop=True)
    raw["rule_label"] = raw["From"].map(lambda f: sender_rule_label(f, "category"))

    model = oof.set_index("review_id")
    missing = sorted(set(raw.loc[raw["rule_label"].isna(), "review_id"]) - set(model.index))
    if missing:
        raise SystemExit(
            f"[category] {len(missing)} non-rule rows have no OOF prediction; "
            f"first ids: {missing[:5]}"
        )

    rows = []
    for row in raw.itertuples():
        if pd.notna(row.rule_label):
            pred_label, confidence, source, fold = row.rule_label, 1.0, "rule", None
        else:
            match = model.loc[row.review_id]
            pred_label = match["pred_label"]
            confidence = float(match["confidence"])
            source = "model"
            fold = int(match["fold"])
        rows.append(
            {
                "dataset": "category_end_to_end",
                "task": "category",
                "review_id": row.review_id,
                "true_label": str(row.category).strip(),
                "pred_label": pred_label,
                "confidence": confidence,
                "source": source,
                "fold": fold,
            }
        )

    out = pd.DataFrame(rows)
    bad = sorted(set(out["pred_label"]) - set(expected_labels))
    if bad:
        raise SystemExit(f"[category] predictions outside taxonomy: {bad}")
    return out


# --- Metrics and bootstrap ---
def bootstrap_metrics(y_true, y_pred, labels, n_boot, seed):
    """Stratified bootstrap CIs for accuracy and macro F1."""
    from sklearn.metrics import accuracy_score, f1_score

    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(y_true == c) for c in np.unique(y_true)]
    accs = np.empty(n_boot)
    f1s = np.empty(n_boot)

    for i in range(n_boot):
        idx = np.concatenate(
            [rng.choice(group, size=len(group), replace=True) for group in groups]
        )
        accs[i] = accuracy_score(y_true[idx], y_pred[idx])
        f1s[i] = f1_score(
            y_true[idx], y_pred[idx], labels=labels, average="macro", zero_division=0
        )

    acc_lo, acc_hi = np.percentile(accs, [2.5, 97.5])
    f1_lo, f1_hi = np.percentile(f1s, [2.5, 97.5])
    return (float(acc_lo), float(acc_hi)), (float(f1_lo), float(f1_hi))


def evaluate_frame(name, task, frame, labels, n_boot, seed, notes=""):
    """Return the summary row for a prediction frame."""
    from sklearn.metrics import accuracy_score, f1_score

    y_true = frame["true_label"].to_numpy()
    y_pred = frame["pred_label"].to_numpy()
    acc_ci, f1_ci = bootstrap_metrics(y_true, y_pred, labels, n_boot, seed)
    acc = accuracy_score(y_true, y_pred)
    f1 = f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    return {
        "dataset": name,
        "task": task,
        "n": len(frame),
        "label_count": len(labels),
        "accuracy": float(acc),
        "accuracy_ci_low": acc_ci[0],
        "accuracy_ci_high": acc_ci[1],
        "macro_f1": float(f1),
        "macro_f1_ci_low": f1_ci[0],
        "macro_f1_ci_high": f1_ci[1],
        "bootstrap": n_boot,
        "seed": seed,
        "notes": notes,
    }


# --- Evaluation steps ---
def load_synthetic(args, tasks, labels, datasets):
    path = None if args.no_synthetic else args.synthetic
    if path and not Path(path).is_file():
        raise SystemExit(f"Synthetic CSV not found: {path} (or pass --no-synthetic)")
    if not path:
        return {}, None

    syn_tasks = (
        ["category", "action"]
        if args.synthetic_tasks == "both"
        else [args.synthetic_tasks]
    )
    syn_data = {}
    for task in tasks:
        if task not in syn_tasks:
            continue
        syn, info = synthetic_dataset(path, task, labels[task], datasets[task])
        syn_data[task] = syn
        print(
            f"[{task}] synthetic rows={info['rows']} "
            f"counts={info['counts']} (train folds only)"
        )
    return syn_data, path


def evaluate_task(task, review, datasets, infos, syn_data, labels, args):
    encoder = args.encoder_category if task == "category" else args.encoder_action
    print(f"[{task}] encoding with {encoder} ...", flush=True)
    oof = oof_for_task(
        task, datasets[task], encoder, syn_data.get(task), args.folds, args.seed
    )

    if task == "action":
        frame = oof.assign(dataset="action")
        notes = "real+synthetic training folds" if task in syn_data else "real data only"
        row = evaluate_frame(
            "action",
            "action",
            frame,
            infos["action"]["supported_labels"],
            args.bootstrap,
            args.seed,
            notes,
        )
        return {"action": frame}, [row]

    category_labels = list(labels["category"])
    model = oof.assign(dataset="category_model")
    e2e = category_end_to_end(review, oof, category_labels)
    rows = [
        evaluate_frame(
            "category_model",
            "category",
            model,
            infos["category"]["supported_labels"],
            args.bootstrap,
            args.seed,
            "head only; Canvas sender-rule rows excluded",
        ),
        evaluate_frame(
            "category_end_to_end",
            "category",
            e2e,
            category_labels,
            args.bootstrap,
            args.seed,
            "sender rule + head; all category rows",
        ),
    ]
    return {"category_model": model, "category_end_to_end": e2e}, rows


def both_labels_summary(eval_frames, args):
    if not {"category_end_to_end", "action"} <= set(eval_frames):
        return None

    cat = eval_frames["category_end_to_end"].set_index("review_id")
    act = eval_frames["action"].set_index("review_id")
    common = sorted(set(cat.index) & set(act.index))
    if not common:
        raise SystemExit("No common review_ids between category and action evaluations")

    correct = (
        (cat.loc[common, "true_label"] == cat.loc[common, "pred_label"]).to_numpy()
        & (act.loc[common, "true_label"] == act.loc[common, "pred_label"]).to_numpy()
    )
    rate = float(correct.mean())
    _, ci_low, ci_high = bootstrap_proportion(correct, args.bootstrap, args.seed)
    print(
        f"[both_labels] n={len(common)} exact-match={rate:.4f} "
        f"95% CI [{ci_low:.4f}, {ci_high:.4f}]"
    )
    return {
        "dataset": "both_labels",
        "task": "both",
        "n": len(common),
        "label_count": None,
        "accuracy": rate,
        "accuracy_ci_low": ci_low,
        "accuracy_ci_high": ci_high,
        "macro_f1": None,
        "macro_f1_ci_low": None,
        "macro_f1_ci_high": None,
        "bootstrap": args.bootstrap,
        "seed": args.seed,
        "notes": "exact match of category and action labels",
    }


# --- Output ---
def write_artifacts(out_dir, summary_rows, oof_frames, manifest):
    summary = pd.DataFrame(summary_rows)
    if "label_count" in summary.columns:
        summary["label_count"] = summary["label_count"].astype("Int64")
    oof = pd.concat(oof_frames, ignore_index=True)
    oof["fold"] = oof["fold"].astype("Int64")
    oof = oof.sort_values(["task", "dataset", "review_id"]).reset_index(drop=True)

    summary.to_csv(out_dir / "offline_f1_summary.csv", index=False, encoding="utf-8-sig")
    oof.to_csv(out_dir / "offline_f1_oof_predictions.csv", index=False, encoding="utf-8-sig")
    (out_dir / "offline_f1_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    report = render_report(summary, manifest)
    (out_dir / "offline_f1_report.txt").write_text(report, encoding="utf-8")
    print("\n" + "=" * 78)
    print(report)
    print("=" * 78)
    print(f"Saved artifacts -> {out_dir}")


def render_report(summary, manifest):
    lines = [
        "Offline macro-F1 — out-of-fold predictions",
        f"Review CSV: {manifest['review_csv']}",
        f"Folds: {manifest['folds']} (stratified) | Bootstrap: {manifest['bootstrap']} "
        f"({manifest['bootstrap_method']}) | Seed: {manifest['seed']}",
        f"Encoders: category={manifest['encoders']['category']}, "
        f"action={manifest['encoders']['action']}",
        f"Synthetic: {manifest['synthetic'] or 'none'}"
        + (f" (tasks: {manifest['synthetic_tasks']})" if manifest["synthetic"] else ""),
        "",
        f"{'Dataset':<24} {'N':>4}  {'Accuracy [95% CI]':<26} {'Macro F1 [95% CI]':<26}",
        "-" * 84,
    ]
    for _, row in summary.iterrows():
        acc = f"{row['accuracy']:.3f} [{row['accuracy_ci_low']:.3f}, {row['accuracy_ci_high']:.3f}]"
        f1 = (
            "—"
            if pd.isna(row["macro_f1"])
            else f"{row['macro_f1']:.3f} "
            f"[{row['macro_f1_ci_low']:.3f}, {row['macro_f1_ci_high']:.3f}]"
        )
        lines.append(f"{row['dataset']:<24} {int(row['n']):>4}  {acc:<26} {f1:<26}")

    both = summary.loc[summary["dataset"] == "both_labels", "n"]
    both_n = int(both.iloc[0]) if len(both) else 0
    rule_n = int(manifest.get("category_rule_rows") or 0)
    rule_note = f"the {rule_n} Canvas sender-rule rows" if rule_n else "Canvas sender-rule rows"
    notes = [
        f"- category_model excludes {rule_note} from the model;",
        "  category_end_to_end includes them (rule + head).",
        "- action uses the configured training condition (real+synthetic by default).",
        f"- both_labels is the exact-match rate on {both_n} unique emails covered by",
        "  both tasks; action rows without a usable category label are excluded.",
        "- CIs are percentile bootstrap intervals; they quantify uncertainty from the",
        "  labelled emails, not from a single held-out split.",
    ]
    return "\n".join(lines + ["", "Notes:", *notes]) + "\n"


def main():
    args = parse_args()
    if args.folds < 2:
        raise SystemExit("--folds must be >= 2")
    if args.bootstrap < 1:
        raise SystemExit("--bootstrap must be >= 1")

    labels, tax_digest = load_taxonomy()
    review = pd.read_csv(args.review, dtype=str, keep_default_na=False)
    tasks = ["category", "action"] if args.task == "both" else [args.task]

    datasets, infos = {}, {}
    for task in tasks:
        datasets[task], infos[task] = task_dataset(
            review, task, labels[task], args.allow_missing_labels
        )
        info = infos[task]
        print(
            f"[{task}] rows={info['rows_used']} counts={info['counts']} "
            f"rule_excluded={info['rule_rows_excluded']} "
            f"supported={info['supported_labels']}"
        )

    syn_data, synthetic_path = load_synthetic(args, tasks, labels, datasets)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows, oof_frames, eval_frames = [], [], {}
    for task in tasks:
        frames, rows = evaluate_task(
            task, review, datasets, infos, syn_data, labels, args
        )
        eval_frames.update(frames)
        oof_frames.extend(frames.values())
        summary_rows.extend(rows)

    both = both_labels_summary(eval_frames, args)
    if both:
        summary_rows.append(both)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "review_csv": display_path(args.review, REPO_ROOT),
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
        "synthetic": display_path(synthetic_path, REPO_ROOT) if syn_data else None,
        "synthetic_tasks": ",".join(sorted(syn_data)) if syn_data else None,
        "rows": {task: len(datasets[task]) for task in tasks},
        "category_rule_rows": infos.get("category", {}).get("rule_rows_excluded"),
        "evaluation_rows": {row["dataset"]: int(row["n"]) for row in summary_rows},
        "versions": {
            pkg: package_version(pkg)
            for pkg in ("numpy", "pandas", "scikit-learn", "torch", "transformers")
        },
    }
    write_artifacts(out_dir, summary_rows, oof_frames, manifest)


if __name__ == "__main__":
    main()
