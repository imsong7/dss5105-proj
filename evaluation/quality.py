"""Offline quality evaluation with bootstrap confidence intervals.

Encoder and ML use out-of-fold predictions or an explicit train/test split.
The LLM is evaluated by app inference.

Usage:
    python evaluation/quality.py
    python evaluation/quality.py --model both
    python evaluation/quality.py --model all
    python evaluation/quality.py --model all --train-review train.csv --test-review test.csv
    python evaluation/quality.py --task action --no-synthetic
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODERS_DIR = REPO_ROOT / "text-encoders"
CLASSICAL_ML_SOURCE = REPO_ROOT / "classical-ml" / "src"
EMAIL_SORTER = REPO_ROOT / "email-sorter"
for _path in (REPO_ROOT, ENCODERS_DIR, CLASSICAL_ML_SOURCE, EMAIL_SORTER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evaluation import (  # noqa: E402
    bootstrap_proportion,
    display_path,
    package_version,
    write_csv,
    write_json,
)
from src.data import (  # noqa: E402
    ENCODERS,
    load_review,
    load_taxonomy,
    synthetic_dataset,
    task_dataset,
)
from src.model import FrozenEncoder, fit_head  # noqa: E402

DEFAULT_REVIEW = REPO_ROOT / "data" / "labels.csv"
DEFAULT_SYNTHETIC = REPO_ROOT / "data" / "synthetic.csv"
DEFAULT_OUT = REPO_ROOT / "evaluation" / "results"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--review",
        help="single labeled file for out-of-fold evaluation (default: shared labels)",
    )
    ap.add_argument("--train-review")
    ap.add_argument("--test-review")
    ap.add_argument("--task", choices=["both", "category", "action"], default="both")
    ap.add_argument(
        "--model",
        choices=["encoder", "ml", "both", "llm", "all"],
        default="encoder",
        help=(
            "model family to evaluate; both compares encoder and ML, "
            "all compares encoder, ML, and LLM"
        ),
    )
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


def selected_model_families(model: str) -> list[str]:
    if model == "both":
        return ["encoder", "ml"]
    if model == "all":
        return ["encoder", "ml", "llm"]
    return [model]


def prediction_frame(
    task: str,
    test_data: pd.DataFrame,
    predicted: np.ndarray,
    family: str,
    confidence: np.ndarray | None = None,
) -> pd.DataFrame:
    frame = test_data[["review_id", "label_key"]].rename(
        columns={"label_key": "true_label"}
    ).copy()
    frame["dataset"] = task
    frame["task"] = task
    frame["pred_label"] = predicted
    frame["confidence"] = confidence if confidence is not None else np.nan
    frame["source"] = family
    frame["fold"] = pd.NA
    frame["model_family"] = family
    return frame[
        [
            "dataset",
            "task",
            "review_id",
            "true_label",
            "pred_label",
            "confidence",
            "source",
            "fold",
            "model_family",
        ]
    ]


def encoder_train_test_for_task(
    task: str,
    train_data: pd.DataFrame,
    test_data: pd.DataFrame,
    encoder_name: str,
    synthetic: pd.DataFrame | None,
) -> pd.DataFrame:
    encoder = FrozenEncoder(encoder_name)
    train_vectors = encoder.encode(train_data["text"].tolist())
    train_labels = train_data["label_key"].tolist()
    if synthetic is not None and not synthetic.empty:
        synthetic_vectors = encoder.encode(synthetic["text"].tolist())
        train_vectors = np.vstack([train_vectors, synthetic_vectors])
        train_labels.extend(synthetic["label_key"].tolist())
    classifier = fit_head(train_vectors, train_labels)
    test_vectors = encoder.encode(test_data["text"].tolist())
    probabilities = classifier.predict_proba(test_vectors)
    return prediction_frame(
        task,
        test_data,
        classifier.classes_[probabilities.argmax(axis=1)].astype(str),
        "encoder",
        probabilities.max(axis=1),
    )


def ml_train_test_for_task(
    task: str,
    train_data: pd.DataFrame,
    test_data: pd.DataFrame,
    synthetic: pd.DataFrame | None,
) -> pd.DataFrame:
    from train_email_ml import build_models

    model_name = "linear_svm" if task == "category" else "complement_nb_balanced"
    task_name = "email_category" if task == "category" else "required_action"
    model = build_models(task_name)[model_name]
    train_text = train_data["text"].tolist()
    train_labels = train_data["label_key"].tolist()
    if synthetic is not None and not synthetic.empty:
        train_text.extend(synthetic["text"].tolist())
        train_labels.extend(synthetic["label_key"].tolist())
    model.fit(train_text, train_labels)
    return prediction_frame(
        task, test_data, model.predict(test_data["text"].tolist()), "ml"
    )


def heldout_predictions(
    task: str,
    train_data: pd.DataFrame,
    test_data: pd.DataFrame,
    synthetic: pd.DataFrame | None,
    args: argparse.Namespace,
) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    frames, rows = {}, []
    for family in selected_model_families(args.model):
        if family == "llm":
            continue
        if family == "encoder":
            encoder_name = (
                args.encoder_category if task == "category" else args.encoder_action
            )
            frame = encoder_train_test_for_task(
                task, train_data, test_data, encoder_name, synthetic
            )
        else:
            frame = ml_train_test_for_task(
                task, train_data, test_data, synthetic
            )
        frames[f"{family}:{task}"] = frame
        notes = (
            "train/test holdout; synthetic rows used in training only"
            if synthetic is not None and not synthetic.empty
            else "train/test holdout"
        )
        if task == "category":
            notes += "; Canvas sender-rule rows excluded"
        rows.append(
            evaluate_frame(
                task,
                task,
                frame,
                train_data["label_key"].drop_duplicates().tolist(),
                args.bootstrap,
                args.seed,
                notes,
                family,
            )
        )
    return frames, rows


# Out-of-fold predictions
def oof_for_task(
    task: str, df: pd.DataFrame, encoder_name: str, syn, folds: int, seed: int
) -> pd.DataFrame:
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


def ml_oof_for_task(
    task: str,
    encoder_data: pd.DataFrame,
    folds: int,
    seed: int,
    use_synthetic: bool,
    synthetic_path: str,
) -> pd.DataFrame:
    """Evaluate the selected classical ML pipeline on the encoder's exact folds."""
    import re

    from sklearn.base import clone
    from sklearn.model_selection import StratifiedKFold

    from app.ml_classifier import ACTION_LABELS, CATEGORY_LABELS
    from train_email_ml import (
        ACTION_VALUE_MAP,
        CATEGORY_VALUE_MAP,
        build_models,
        normalise,
        prepare_synthetic,
        read_labeled_data,
        remove_duplicates_and_check_conflicts,
    )
    task_name = "email_category" if task == "category" else "required_action"
    category_data, action_data, _ = read_labeled_data()
    ml_data = category_data if task == "category" else action_data
    ml_data = remove_duplicates_and_check_conflicts(ml_data, task_name).copy()
    label_map = CATEGORY_LABELS if task == "category" else ACTION_LABELS
    value_map = CATEGORY_VALUE_MAP if task == "category" else ACTION_VALUE_MAP
    ml_data["label_key"] = ml_data["label"].map(
        lambda value: label_map.get(re.sub(r"[^a-z0-9]+", "", str(value).lower()))
    )
    if ml_data["label_key"].isna().any():
        raise ValueError(f"Unmapped labels found in ML {task} data.")

    ml_by_id = ml_data.set_index("message_id")
    if ml_by_id.index.has_duplicates:
        raise ValueError(f"Duplicate message IDs found in ML {task} data.")
    review_ids = encoder_data["review_id"].astype(str)
    if set(review_ids) != set(ml_by_id.index.astype(str)):
        raise ValueError(f"ML and encoder review IDs differ for {task}.")
    ml_data = ml_by_id.loc[review_ids].reset_index()
    if not np.array_equal(
        encoder_data["label_key"].astype(str).to_numpy(),
        ml_data["label_key"].astype(str).to_numpy(),
    ):
        raise ValueError(f"ML and encoder labels differ for {task}.")

    synthetic = pd.DataFrame(columns=["text", "label"])
    if use_synthetic and task == "action":
        raw_synthetic = pd.read_csv(
            synthetic_path, dtype=str, keep_default_na=False, encoding="utf-8-sig"
        )
        if not {"Subject", "Preview", "action"} <= set(raw_synthetic.columns):
            raise ValueError("Synthetic CSV needs Subject, Preview, and action columns.")
        synthetic = pd.DataFrame(
            {
                "text": (
                    raw_synthetic["Subject"].str.strip()
                    + "\n"
                    + raw_synthetic["Preview"].str.strip()
                ).str.strip(),
                "label": raw_synthetic["action"].map(
                    lambda value: value_map.get(normalise(value))
                ),
            }
        )
        if synthetic["label"].isna().any():
            unknown = sorted(
                raw_synthetic.loc[synthetic["label"].isna(), "action"]
                .astype(str)
                .unique()
            )
            raise ValueError(
                f"Unknown synthetic action values: {unknown}"
            )
        synthetic = synthetic[synthetic["text"].ne("")].copy()
        synthetic = prepare_synthetic(synthetic, ml_data)
        synthetic["label"] = synthetic["label"].map(
            lambda value: label_map.get(
                re.sub(r"[^a-z0-9]+", "", str(value).lower())
            )
        )
        synthetic = synthetic[synthetic["label"].notna()]

    model_name = "linear_svm" if task == "category" else "complement_nb_balanced"
    model = build_models(task_name)[model_name]
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    frames = []
    for fold, (train_idx, test_idx) in enumerate(
        cv.split(encoder_data, encoder_data["label_key"]), 1
    ):
        train = ml_data.iloc[train_idx]
        test = ml_data.iloc[test_idx]
        train_text = train["text"].tolist()
        train_labels = train["label_key"].tolist()
        if not synthetic.empty:
            validation_keys = set(test["text"].map(normalise))
            extra = synthetic[~synthetic["text"].map(normalise).isin(validation_keys)]
            train_text.extend(extra["text"].tolist())
            train_labels.extend(extra["label"].tolist())
        fitted = clone(model).fit(train_text, train_labels)
        predictions = fitted.predict(test["text"].tolist())
        frame = test[["message_id", "label_key"]].rename(
            columns={"message_id": "review_id", "label_key": "true_label"}
        )
        frame["dataset"] = task
        frame["task"] = task
        frame["pred_label"] = predictions
        frame["confidence"] = np.nan
        frame["source"] = "ml"
        frame["fold"] = fold
        frames.append(
            frame[
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
    if len(out) != len(encoder_data) or out["review_id"].duplicated().any():
        raise SystemExit(f"[{task}] invalid ML OOF prediction count.")
    return out


def llm_predictions(datasets: dict, predictor=None) -> dict[str, pd.DataFrame]:
    """Classify each unique review once with the app's LLM backend."""
    from app.models import Email

    if predictor is None:
        from app.llama_classifier import EmailClassifier

        predictor = EmailClassifier()

    input_columns = ["review_id", "Subject", "From", "Preview", "Received DateTime"]
    available_columns = ["review_id", "Subject", "From", "Preview"]
    if any(not set(available_columns) <= set(frame.columns) for frame in datasets.values()):
        raise ValueError("LLM evaluation requires review_id, Subject, From, and Preview.")

    inputs = pd.concat(
        [frame.reindex(columns=input_columns) for frame in datasets.values()],
        ignore_index=True,
    ).rename(columns={"Received DateTime": "received"})
    inputs["review_id"] = inputs["review_id"].astype(str)
    for column in ("Subject", "From", "Preview", "received"):
        inputs[column] = inputs[column].fillna("").astype(str)
    email_columns = ["Subject", "From", "Preview", "received"]
    conflicting = (
        inputs.groupby("review_id")[email_columns].nunique().gt(1).any(axis=1)
    )
    if conflicting.any():
        ids = conflicting[conflicting].index.tolist()[:5]
        raise ValueError(f"Conflicting email inputs across evaluation tasks: {ids}")
    inputs = inputs.drop_duplicates("review_id").sort_values("review_id")

    print(f"[llm] classifying {len(inputs)} unique labeled emails ...", flush=True)
    predictions = {}
    for index, row in enumerate(inputs.itertuples(index=False), 1):
        result = predictor.classify(
            Email(
                id=row.review_id,
                subject=row.Subject,
                sender=row.From,
                received=row.received,
                preview=row.Preview,
            )
        )
        predictions[row.review_id] = {
            "category": str(result.content_category).strip().lower().replace(" ", "_"),
            "action": str(result.reply_nature).strip().lower().replace(" ", "_"),
        }
        if index == 1 or index % 10 == 0 or index == len(inputs):
            print(f"[llm] completed {index}/{len(inputs)}", flush=True)

    frames = {}
    for task, dataset in datasets.items():
        frame = dataset[["review_id", "label_key"]].rename(
            columns={"label_key": "true_label"}
        ).copy()
        frame["review_id"] = frame["review_id"].astype(str)
        frame["dataset"] = task
        frame["task"] = task
        frame["pred_label"] = frame["review_id"].map(
            {review_id: pred[task] for review_id, pred in predictions.items()}
        )
        if frame["pred_label"].isna().any():
            raise ValueError(f"Missing LLM predictions for {task} evaluation rows.")
        frame["confidence"] = np.nan
        frame["source"] = "llm"
        frame["fold"] = pd.NA
        frame["model_family"] = "llm"
        frames[task] = frame[
            [
                "dataset",
                "task",
                "review_id",
                "true_label",
                "pred_label",
                "confidence",
                "source",
                "fold",
                "model_family",
            ]
        ]
    return frames


# Metrics and bootstrap
def bootstrap_metrics(y_true, y_pred, labels, n_boot: int, seed: int) -> tuple:
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


def evaluate_frame(
    name: str,
    task: str,
    frame: pd.DataFrame,
    labels: list,
    n_boot: int,
    seed: int,
    notes: str = "",
    model_family: str = "encoder",
) -> dict:
    """Return the summary row for a prediction frame."""
    from sklearn.metrics import accuracy_score, f1_score

    y_true = frame["true_label"].to_numpy()
    y_pred = frame["pred_label"].to_numpy()
    acc_ci, f1_ci = bootstrap_metrics(y_true, y_pred, labels, n_boot, seed)
    acc = accuracy_score(y_true, y_pred)
    f1 = f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    return {
        "dataset": name,
        "model_family": model_family,
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


# Evaluation steps
def load_synthetic(
    args: argparse.Namespace,
    tasks: list,
    labels: dict,
    datasets: dict,
    exclude_datasets: dict | None = None,
) -> tuple:
    if args.no_synthetic:
        return {}, None
    path = args.synthetic
    if not Path(path).is_file():
        raise SystemExit(f"Synthetic CSV not found: {path} (or pass --no-synthetic)")

    syn_tasks = (
        ["category", "action"]
        if args.synthetic_tasks == "both"
        else [args.synthetic_tasks]
    )
    syn_data = {}
    for task in tasks:
        if task not in syn_tasks:
            continue
        reference = datasets[task]
        if exclude_datasets and task in exclude_datasets:
            reference = pd.concat(
                [reference, exclude_datasets[task]], ignore_index=True
            )
        syn, info = synthetic_dataset(path, task, labels[task], reference)
        syn_data[task] = syn
        print(
            f"[{task}] synthetic rows={info['rows']} "
            f"counts={info['counts']} (train folds only)"
        )
    return syn_data, path


def evaluate_task(
    task: str,
    datasets: dict,
    infos: dict,
    syn_data,
    args: argparse.Namespace,
) -> tuple:
    frames, rows = {}, []
    model_families = [
        family for family in selected_model_families(args.model) if family != "llm"
    ]
    for family_index, family in enumerate(model_families):
        if family == "encoder":
            encoder = (
                args.encoder_category if task == "category" else args.encoder_action
            )
            print(f"[{task}] encoding with {encoder} ...", flush=True)
            oof = oof_for_task(
                task, datasets[task], encoder, syn_data.get(task),
                args.folds, args.seed,
            )
        else:
            print(f"[{task}] evaluating classical ML ...", flush=True)
            oof = ml_oof_for_task(
                task,
                datasets[task],
                args.folds,
                args.seed,
                task in syn_data,
                args.synthetic,
            )
        oof["model_family"] = family
        model_seed = args.seed + family_index

        if task == "action":
            frame = oof.assign(dataset="action")
            frames[f"{family}:action"] = frame
            notes = (
                "real+synthetic training folds"
                if task in syn_data
                else "real data only"
            )
            rows.append(
                evaluate_frame(
                    "action", task, frame, infos[task]["supported_labels"],
                    args.bootstrap, model_seed, notes, family,
                )
            )
            continue

        frame = oof.assign(dataset="category")
        frames[f"{family}:category"] = frame
        rows.append(
            evaluate_frame(
                "category", task, frame,
                infos[task]["supported_labels"], args.bootstrap,
                model_seed, "classifier only; Canvas sender-rule rows excluded",
                family,
            )
        )
    return frames, rows


def both_summary(eval_frames: dict, args: argparse.Namespace) -> list[dict]:
    rows = []
    families = [
        family
        for family in ("encoder", "ml", "llm")
        if f"{family}:category" in eval_frames
    ]
    for family in families:
        cat_key, action_key = (
            f"{family}:category",
            f"{family}:action",
        )
        if cat_key not in eval_frames or action_key not in eval_frames:
            continue
        cat = eval_frames[cat_key].set_index("review_id")
        act = eval_frames[action_key].set_index("review_id")
        common = sorted(set(cat.index) & set(act.index))
        if not common:
            raise SystemExit(
                f"No common review_ids between {family} category and action results"
            )

        correct = (
            (cat.loc[common, "true_label"] == cat.loc[common, "pred_label"]).to_numpy()
            & (act.loc[common, "true_label"] == act.loc[common, "pred_label"]).to_numpy()
        )
        rate = float(correct.mean())
        _, ci_low, ci_high = bootstrap_proportion(
            correct, args.bootstrap, args.seed
        )
        print(
            f"[{family}:both] n={len(common)} exact-match={rate:.4f} "
            f"95% CI [{ci_low:.4f}, {ci_high:.4f}]"
        )
        rows.append(
            {
                "dataset": "both",
                "model_family": family,
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
        )
    return rows


# Output
def write_artifacts(
    out_dir: Path, summary_rows: list, prediction_frames: list, manifest: dict
) -> None:
    summary = pd.DataFrame(summary_rows)
    if "label_count" in summary.columns:
        summary["label_count"] = summary["label_count"].astype("Int64")
    predictions = pd.concat(prediction_frames, ignore_index=True)
    predictions["fold"] = predictions["fold"].astype("Int64")
    predictions = predictions.sort_values(
        ["model_family", "task", "dataset", "review_id"]
    ).reset_index(drop=True)

    write_csv(summary, out_dir / "quality_summary.csv")
    write_csv(predictions, out_dir / "quality_predictions.csv")
    plot_offline_quality(summary, out_dir / "quality_comparison.png")
    write_json(manifest, out_dir / "quality_manifest.json")
    report = render_report(summary, manifest)
    print("\n" + "=" * 78)
    print(report)
    print("=" * 78)
    print(f"Saved artifacts -> {out_dir}")


def plot_offline_quality(summary: pd.DataFrame, path: Path) -> None:
    """Plot macro-F1 and accuracy with their bootstrap confidence intervals."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    families = [
        family for family in ("encoder", "ml", "llm")
        if family in set(summary["model_family"])
    ]
    datasets = list(dict.fromkeys(summary["dataset"].tolist()))
    if not families or not datasets:
        raise ValueError("Offline quality summary has no model or dataset rows.")

    colors = {"encoder": "#4472C4", "ml": "#ED7D31", "llm": "#70AD47"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    positions = np.arange(len(datasets), dtype=float)
    width = min(0.34, 0.72 / len(families))
    metrics = (
        ("macro_f1", "Macro F1", "macro_f1_ci_low", "macro_f1_ci_high"),
        ("accuracy", "Accuracy", "accuracy_ci_low", "accuracy_ci_high"),
    )

    for ax, (metric, title, low_col, high_col) in zip(axes, metrics):
        for family_index, family in enumerate(families):
            values = []
            lows = []
            highs = []
            xs = []
            family_rows = summary[summary["model_family"] == family].set_index("dataset")
            for dataset_index, dataset in enumerate(datasets):
                if dataset not in family_rows.index:
                    continue
                row = family_rows.loc[dataset]
                value = row[metric]
                if pd.isna(value):
                    continue
                values.append(float(value))
                lows.append(max(0.0, float(value) - float(row[low_col])))
                highs.append(max(0.0, float(row[high_col]) - float(value)))
                xs.append(
                    positions[dataset_index]
                    + (family_index - (len(families) - 1) / 2) * width
                )
            if values:
                ax.bar(
                    xs,
                    values,
                    width,
                    label=family,
                    color=colors.get(family),
                    yerr=np.array([lows, highs]),
                    capsize=3,
                )
        ax.set_title(title)
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("Score")
        ax.set_xticks(positions)
        ax.set_xticklabels(
            [dataset.replace("_", "\n") for dataset in datasets],
            rotation=0,
            fontsize=8,
        )
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)

    axes[0].legend(title="Model family")
    fig.suptitle("Offline quality comparison (95% bootstrap CI)")
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def render_report(summary: pd.DataFrame, manifest: dict) -> str:
    def ci(value, low, high):
        return f"{value:.3f} [{low:.3f}, {high:.3f}]"

    if manifest["evaluation_mode"] == "train_test":
        evaluation_description = "Train/test evaluation"
        data_description = (
            f"Training data: {manifest['train_file']} | "
            f"Test data: {manifest['test_file']}"
        )
    elif any(family in manifest["model_families"] for family in ("encoder", "ml")):
        evaluation_description = f"{manifest['folds']} stratified folds"
        data_description = f"Review data: {manifest['review_file']}"
    else:
        evaluation_description = "LLM inference"
        data_description = f"Review data: {manifest['review_file']}"
    lines = [
        "Offline quality — held-out / inference predictions",
        data_description,
        f"Evaluation: {evaluation_description} | Bootstrap: {manifest['bootstrap']} "
        f"({manifest['bootstrap_method']}) | Seed: {manifest['seed']}",
        f"Encoders: category={manifest['encoders']['category']}, "
        f"action={manifest['encoders']['action']}",
        f"Model families: {', '.join(manifest['model_families'])}",
        *(
            [f"LLM: {manifest['llm_model']}"]
            if manifest.get("llm_model")
            else []
        ),
        f"Synthetic: {manifest['synthetic'] or 'none'}"
        + (f" (tasks: {manifest['synthetic_tasks']})" if manifest["synthetic"] else ""),
        "",
        f"{'Model':<8} {'Dataset':<24} {'N':>4}  "
        f"{'Accuracy [95% CI]':<26} {'Macro F1 [95% CI]':<26}",
        "-" * 84,
    ]
    for _, row in summary.iterrows():
        acc = ci(row["accuracy"], row["accuracy_ci_low"], row["accuracy_ci_high"])
        f1 = (
            "—"
            if pd.isna(row["macro_f1"])
            else ci(row["macro_f1"], row["macro_f1_ci_low"], row["macro_f1_ci_high"])
        )
        lines.append(
            f"{row['model_family']:<8} {row['dataset']:<24} "
            f"{int(row['n']):>4}  {acc:<26} {f1:<26}"
        )

    notes = []
    if "category" in manifest["tasks"]:
        notes.append("- category is classifier-only; Canvas sender-rule emails are excluded.")
    if manifest["synthetic"]:
        notes.append(
            "- Synthetic rows were added to encoder/ML training data only."
            if manifest["evaluation_mode"] == "train_test"
            else "- Synthetic rows enter encoder/ML training folds only."
        )
    else:
        notes.append("- No synthetic rows were used.")
    if manifest["evaluation_mode"] == "train_test":
        method_note = "- Encoder/ML use the training file."
        if "llm" in manifest["model_families"]:
            method_note += " LLM predictions use app inference."
    else:
        method_note = "- Encoder/ML predictions are out-of-fold."
        if "llm" in manifest["model_families"]:
            method_note += " LLM predictions use app inference."
    notes.append(method_note)
    if manifest["task"] == "both":
        notes.append(
            "- both requires category and action to be correct; Canvas rule rows are excluded."
        )
    notes.append("- ML confidence is unavailable; LLM confidence is not reported.")
    notes.append(
        "- CIs are percentile bootstrap intervals over the held-out labeled rows."
        if manifest["evaluation_mode"] == "train_test"
        else "- CIs are percentile bootstrap intervals over the labeled emails, not"
        "\n  model-training or split variability."
    )
    return "\n".join(lines + ["", "Notes:", *notes]) + "\n"


def main() -> None:
    args = parse_args()
    has_train_test = bool(args.train_review or args.test_review)
    if bool(args.train_review) != bool(args.test_review):
        raise SystemExit("Pass both --train-review and --test-review.")
    if has_train_test and args.review:
        raise SystemExit("--review cannot be combined with --train-review/--test-review.")
    if not has_train_test and args.folds < 2:
        raise SystemExit("--folds must be >= 2")
    if args.bootstrap < 1:
        raise SystemExit("--bootstrap must be >= 1")

    labels, tax_digest = load_taxonomy()
    tasks = ["category", "action"] if args.task == "both" else [args.task]

    if has_train_test:
        train_review = load_review(args.train_review)
        test_review = load_review(args.test_review)
        for name, review_frame in (
            ("training", train_review),
            ("test", test_review),
        ):
            if "review_id" not in review_frame:
                raise SystemExit(f"{name} review file needs a review_id column.")
            review_frame["review_id"] = (
                review_frame["review_id"].fillna("").astype(str).str.strip()
            )
            ids = review_frame["review_id"]
            if ids.eq("").any() or ids.duplicated().any():
                raise SystemExit(
                    f"{name} review file has empty or duplicate review IDs."
                )
        overlap = set(train_review["review_id"].astype(str)) & set(
            test_review["review_id"].astype(str)
        )
        if overlap:
            raise SystemExit(
                f"Training and test files share review IDs: {sorted(overlap)[:5]}"
            )

        train_datasets, train_infos = {}, {}
        datasets, infos = {}, {}
        for task in tasks:
            train_datasets[task], train_infos[task] = task_dataset(
                train_review,
                task,
                labels[task],
                args.allow_missing_labels,
                training=True,
            )
            datasets[task], infos[task] = task_dataset(
                test_review,
                task,
                labels[task],
                allow_missing=True,
                training=False,
            )
            if train_datasets[task].empty or datasets[task].empty:
                raise SystemExit(f"[{task}] training and test files need usable rows.")
            train_labels = set(train_datasets[task]["label_key"])
            test_labels = set(datasets[task]["label_key"])
            if not test_labels <= train_labels:
                raise SystemExit(
                    f"[{task}] test labels have no training examples: "
                    f"{sorted(test_labels - train_labels)}"
                )
            text_overlap = set(train_datasets[task]["text"]) & set(
                datasets[task]["text"]
            )
            if text_overlap:
                raise SystemExit(
                    f"[{task}] identical model inputs occur in train and test files."
                )
    else:
        review_path = args.review or str(DEFAULT_REVIEW)
        review = load_review(review_path)
        train_datasets = None
        train_infos = None
        datasets, infos = {}, {}
        for task in tasks:
            datasets[task], infos[task] = task_dataset(
                review, task, labels[task], args.allow_missing_labels
            )

    metric_infos = train_infos if has_train_test else infos
    for task in tasks:
        info = infos[task]
        print(
            f"[{task}] rows={info['rows_used']} counts={info['counts']} "
            f"rule_excluded={info['rule_rows_excluded']} "
            f"supported={info['supported_labels']}"
        )

    model_families = selected_model_families(args.model)
    if any(family in model_families for family in ("encoder", "ml")):
        syn_data, synthetic_path = load_synthetic(
            args,
            tasks,
            labels,
            train_datasets if has_train_test else datasets,
            exclude_datasets=datasets if has_train_test else None,
        )
    else:
        syn_data, synthetic_path = {}, None
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows, prediction_frames, eval_frames = [], [], {}
    for task in tasks:
        if has_train_test:
            frames, rows = heldout_predictions(
                task, train_datasets[task], datasets[task], syn_data.get(task), args
            )
        else:
            frames, rows = evaluate_task(task, datasets, infos, syn_data, args)
        eval_frames.update(frames)
        prediction_frames.extend(frames.values())
        summary_rows.extend(rows)

    if "llm" in model_families:
        llm_frames = llm_predictions(datasets)
        for task, frame in llm_frames.items():
            eval_frames[f"llm:{task}"] = frame
            prediction_frames.append(frame)
            summary_rows.append(
                evaluate_frame(
                    task,
                    task,
                    frame,
                    metric_infos[task]["supported_labels"],
                    args.bootstrap,
                    args.seed,
                    "app LLM inference; no synthetic training data",
                    "llm",
                )
            )

    summary_rows.extend(both_summary(eval_frames, args))

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_mode": "train_test" if has_train_test else "out_of_fold",
        "review_file": (
            display_path(args.review or str(DEFAULT_REVIEW), REPO_ROOT)
            if not has_train_test
            else None
        ),
        "train_file": (
            display_path(args.train_review, REPO_ROOT) if has_train_test else None
        ),
        "test_file": (
            display_path(args.test_review, REPO_ROOT) if has_train_test else None
        ),
        "taxonomy_sha256_16": tax_digest,
        "task": args.task,
        "tasks": tasks,
        "folds": None if has_train_test else args.folds,
        "bootstrap": args.bootstrap,
        "bootstrap_method": "stratified by true label (percentile CI)",
        "seed": args.seed,
        "model_families": model_families,
        "prediction_methods": {
            family: (
                "stratified out-of-fold"
                if family in {"encoder", "ml"}
                else "pretrained app inference"
            )
            for family in model_families
        },
        "ml_estimators": {
            "category": "linear_svm",
            "action": "complement_nb_balanced",
        } if "ml" in model_families else None,
        "llm_model": None,
        "encoders": {
            "category": args.encoder_category,
            "action": args.encoder_action,
        },
        "synthetic": display_path(synthetic_path, REPO_ROOT) if syn_data else None,
        "synthetic_tasks": ",".join(sorted(syn_data)) if syn_data else None,
        "rows": {task: len(datasets[task]) for task in tasks},
        "training_rows": (
            {task: len(train_datasets[task]) for task in tasks}
            if has_train_test
            else None
        ),
        "category_rule_rows": infos.get("category", {}).get("rule_rows_excluded"),
        "evaluation_rows": {row["dataset"]: int(row["n"]) for row in summary_rows},
        "versions": {
            pkg: package_version(pkg)
            for pkg in ("numpy", "pandas", "scikit-learn", "torch", "transformers")
        },
    }
    if "llm" in model_families:
        from app.config import settings

        manifest["llm_model"] = settings.ollama_model
    write_artifacts(out_dir, summary_rows, prediction_frames, manifest)


if __name__ == "__main__":
    main()
