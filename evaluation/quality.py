"""Offline quality evaluation: accuracy and macro F1 per method.

Encoder and ML use out-of-fold predictions. The LLM is evaluated by app
inference, Claude by the inbox-sorter pipeline.

Usage:
    python evaluation/quality.py
    python evaluation/quality.py --model both
    python evaluation/quality.py --model all
    python evaluation/quality.py --model claude --claude-limit 50
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

# Families scored by running the model on the labelled emails, not by
# out-of-fold training.
INFERENCE_FAMILIES = {"llm", "claude"}


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--review",
        help="labeled file for out-of-fold evaluation (default: shared labels)",
    )
    ap.add_argument("--task", choices=["both", "category", "action"], default="both")
    ap.add_argument(
        "--model",
        choices=["encoder", "ml", "both", "llm", "claude", "all"],
        default="encoder",
        help=(
            "model family to evaluate; both compares encoder and ML, "
            "all compares encoder, ML, LLM and Claude"
        ),
    )
    ap.add_argument(
        "--claude-limit",
        type=int,
        default=0,
        help="max unique emails sent to the Claude API; 0 = all (API calls cost money)",
    )
    ap.add_argument("--folds", type=int, default=5)
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
    return ap.parse_args(argv)


def selected_model_families(model: str) -> list[str]:
    if model == "both":
        return ["encoder", "ml"]
    if model == "all":
        return ["encoder", "ml", "llm", "claude"]
    return [model]


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
    from sklearn.base import clone
    from sklearn.model_selection import StratifiedKFold

    from app.ml_classifier import ACTION_LABELS, CATEGORY_LABELS
    from comparison import build_models, filtered_synthetic
    from train_email_ml import (
        ACTION_VALUE_MAP,
        CATEGORY_VALUE_MAP,
        normalise,
        read_workbook,
        remove_duplicates_and_check_conflicts,
    )

    task_name = "email_category" if task == "category" else "required_action"
    category_data, action_data, _ = read_workbook()
    ml_data = category_data if task == "category" else action_data
    ml_data = remove_duplicates_and_check_conflicts(ml_data, task_name).copy()
    label_map = CATEGORY_LABELS if task == "category" else ACTION_LABELS
    value_map = CATEGORY_VALUE_MAP if task == "category" else ACTION_VALUE_MAP
    ml_data["label_key"] = ml_data["label"].map(
        lambda value: label_map.get(normalise(value))
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
        synthetic = synthetic[synthetic["text"].ne("")].copy()
        synthetic["label"] = synthetic["label"].map(
            lambda value: label_map.get(normalise(value))
        )
        synthetic = synthetic[synthetic["label"].notna()]
        synthetic = filtered_synthetic(synthetic, ml_data)

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


def _unique_email_inputs(datasets: dict, family: str) -> pd.DataFrame:
    """One row per unique email, shared by the inference-based families."""
    input_columns = ["review_id", "Subject", "From", "Preview", "Received DateTime"]
    available_columns = ["review_id", "Subject", "From", "Preview"]
    if any(not set(available_columns) <= set(frame.columns) for frame in datasets.values()):
        raise ValueError(
            f"{family} evaluation requires review_id, Subject, From, and Preview."
        )

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
    return inputs.drop_duplicates("review_id").sort_values("review_id")


def _prediction_frames(
    datasets: dict, predictions: dict, family: str
) -> dict[str, pd.DataFrame]:
    """Turn one prediction per email into one prediction frame per task."""
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
            raise ValueError(f"Missing {family} predictions for {task} evaluation rows.")
        frame["confidence"] = np.nan
        frame["source"] = family
        frame["fold"] = pd.NA
        frame["model_family"] = family
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


def llm_predictions(datasets: dict, predictor=None) -> dict[str, pd.DataFrame]:
    """Classify each unique review once with the app's LLM backend."""
    from app.models import Email

    if predictor is None:
        from app.llama_classifier import EmailClassifier

        predictor = EmailClassifier()

    inputs = _unique_email_inputs(datasets, "LLM")

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

    return _prediction_frames(datasets, predictions, "llm")


def claude_predictions(
    datasets: dict, predictor=None, limit: int = 0
) -> dict[str, pd.DataFrame]:
    """Classify each unique review once with the inbox-sorter pipeline.

    The inbox-sorter answers topic and action in one API call, and its labels
    are translated to the email-sorter taxonomy by the adapter.
    """
    from app.models import Email

    if predictor is None:
        from evaluation.inbox_sorter import InboxSorterBackend

        predictor = InboxSorterBackend()

    inputs = _unique_email_inputs(datasets, "Claude")
    total = len(inputs)
    if limit:
        inputs = inputs.head(limit)
    keep = set(inputs["review_id"])
    limited = {
        task: dataset[dataset["review_id"].astype(str).isin(keep)].copy()
        for task, dataset in datasets.items()
    }
    print(
        f"[claude] classifying {len(inputs)} of {total} unique labeled emails "
        "with the Anthropic API ...",
        flush=True,
    )

    predictions = {}
    for index, row in enumerate(inputs.itertuples(index=False), 1):
        result = predictor.predict(
            Email(
                id=row.review_id,
                subject=row.Subject,
                sender=row.From,
                received=row.received,
                preview=row.Preview,
            )
        )
        predictions[row.review_id] = {
            "category": str(result.category).strip().lower().replace(" ", "_"),
            "action": str(result.action).strip().lower().replace(" ", "_"),
        }
        if index == 1 or index % 10 == 0 or index == len(inputs):
            print(f"[claude] completed {index}/{len(inputs)}", flush=True)

    return _prediction_frames(limited, predictions, "claude")


# Metrics
def evaluate_frame(
    name: str,
    task: str,
    frame: pd.DataFrame,
    labels: list,
    notes: str = "",
    model_family: str = "encoder",
) -> dict:
    """Return the summary row for a prediction frame."""
    from sklearn.metrics import accuracy_score, f1_score

    y_true = frame["true_label"].to_numpy()
    y_pred = frame["pred_label"].to_numpy()
    return {
        "dataset": name,
        "model_family": model_family,
        "task": task,
        "n": len(frame),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(
            f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
        ),
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
        family
        for family in selected_model_families(args.model)
        if family not in INFERENCE_FAMILIES
    ]
    for family in model_families:
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
                    notes, family,
                )
            )
            continue

        frame = oof.assign(dataset="category")
        frames[f"{family}:category"] = frame
        rows.append(
            evaluate_frame(
                "category", task, frame,
                infos[task]["supported_labels"],
                "classifier only; Canvas sender-rule rows excluded",
                family,
            )
        )
    return frames, rows


# Output
def write_artifacts(
    out_dir: Path, summary_rows: list, prediction_frames: list, manifest: dict
) -> None:
    summary = pd.DataFrame(summary_rows)
    predictions = pd.concat(prediction_frames, ignore_index=True)
    predictions["fold"] = predictions["fold"].astype("Int64")
    predictions = predictions.sort_values(
        ["model_family", "task", "dataset", "review_id"]
    ).reset_index(drop=True)

    write_csv(summary, out_dir / "offline_quality_summary.csv")
    write_csv(predictions, out_dir / "offline_quality_predictions.csv")
    plot_offline_quality(summary, out_dir / "offline_quality_comparison.png")
    write_json(manifest, out_dir / "offline_quality_manifest.json")
    report = render_report(summary, manifest)
    print("\n" + "=" * 78)
    print(report)
    print("=" * 78)
    print(f"Saved artifacts -> {out_dir}")


def plot_offline_quality(summary: pd.DataFrame, path: Path) -> None:
    """Plot accuracy and macro F1 per method."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    families = [
        family for family in ("encoder", "ml", "llm", "claude")
        if family in set(summary["model_family"])
    ]
    datasets = list(dict.fromkeys(summary["dataset"].tolist()))
    if not families or not datasets:
        raise ValueError("Offline quality summary has no model or dataset rows.")

    colors = {
        "encoder": "#4472C4",
        "ml": "#ED7D31",
        "llm": "#70AD47",
        "claude": "#7030A0",
    }
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    positions = np.arange(len(datasets), dtype=float)
    width = min(0.34, 0.72 / len(families))
    metrics = (("macro_f1", "Macro F1"), ("accuracy", "Accuracy"))

    for ax, (metric, title) in zip(axes, metrics):
        for family_index, family in enumerate(families):
            values, xs = [], []
            family_rows = summary[summary["model_family"] == family].set_index("dataset")
            for dataset_index, dataset in enumerate(datasets):
                if dataset not in family_rows.index:
                    continue
                value = family_rows.loc[dataset, metric]
                if pd.isna(value):
                    continue
                values.append(float(value))
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
    fig.suptitle("Offline quality comparison")
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def render_report(summary: pd.DataFrame, manifest: dict) -> str:
    lines = [
        "Offline quality — held-out / inference predictions",
        f"Review data: {manifest['review_file']}",
        f"Evaluation: {manifest['folds']} stratified folds | Seed: {manifest['seed']}",
        f"Encoders: category={manifest['encoders']['category']}, "
        f"action={manifest['encoders']['action']}",
        f"Model families: {', '.join(manifest['model_families'])}",
        *([f"LLM: {manifest['llm_model']}"] if manifest.get("llm_model") else []),
        *([f"Claude: {manifest['claude_model']}"] if manifest.get("claude_model") else []),
        f"Synthetic: {manifest['synthetic'] or 'none'}"
        + (f" (tasks: {manifest['synthetic_tasks']})" if manifest["synthetic"] else ""),
        "",
        f"{'Model':<8} {'Dataset':<10} {'N':>4} {'Accuracy':>9} {'Macro F1':>9}",
        "-" * 46,
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"{row['model_family']:<8} {row['dataset']:<10} {int(row['n']):>4} "
            f"{row['accuracy']:>9.3f} {row['macro_f1']:>9.3f}"
        )

    notes = []
    if "category" in manifest["tasks"]:
        notes.append("- category excludes Canvas sender-rule emails.")
    notes.append(
        "- Synthetic rows enter encoder/ML training folds only."
        if manifest["synthetic"]
        else "- No synthetic rows were used."
    )
    if any(family in manifest["model_families"] for family in ("encoder", "ml")):
        notes.append("- Encoder/ML predictions are out-of-fold.")
    inference_families = [
        family
        for family in ("llm", "claude")
        if family in manifest["model_families"]
    ]
    if inference_families:
        notes.append(
            "- "
            + " and ".join(inference_families).capitalize()
            + " predictions use one API call per email."
        )
    if "claude" in manifest["model_families"]:
        notes.append(
            "- Claude is the inbox-sorter pipeline as configured "
            "(rules -> Claude -> guardrails)."
        )
    return "\n".join(lines + ["", "Notes:", *notes]) + "\n"


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.folds < 2:
        raise SystemExit("--folds must be >= 2")
    if args.claude_limit < 0:
        raise SystemExit("--claude-limit must be >= 0")

    labels, tax_digest = load_taxonomy()
    tasks = ["category", "action"] if args.task == "both" else [args.task]

    review_path = args.review or str(DEFAULT_REVIEW)
    review = load_review(review_path)
    datasets, infos = {}, {}
    for task in tasks:
        datasets[task], infos[task] = task_dataset(
            review, task, labels[task], args.allow_missing_labels
        )

    for task in tasks:
        info = infos[task]
        print(
            f"[{task}] rows={info['rows_used']} counts={info['counts']} "
            f"rule_excluded={info['rule_rows_excluded']} "
            f"supported={info['supported_labels']}"
        )

    model_families = selected_model_families(args.model)
    if "claude" in model_families:
        unique = len(
            {
                str(review_id)
                for frame in datasets.values()
                for review_id in frame["review_id"]
            }
        )
        planned = min(unique, args.claude_limit) if args.claude_limit else unique
        print(
            f"[claude] about {planned} Anthropic API calls (one per unique email); "
            "use --claude-limit to cap the sample.",
            flush=True,
        )
    if any(family in model_families for family in ("encoder", "ml")):
        syn_data, synthetic_path = load_synthetic(args, tasks, labels, datasets)
    else:
        syn_data, synthetic_path = {}, None
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows, prediction_frames = [], []
    for task in tasks:
        frames, rows = evaluate_task(task, datasets, infos, syn_data, args)
        prediction_frames.extend(frames.values())
        summary_rows.extend(rows)

    if "llm" in model_families:
        for task, frame in llm_predictions(datasets).items():
            prediction_frames.append(frame)
            summary_rows.append(
                evaluate_frame(
                    task,
                    task,
                    frame,
                    infos[task]["supported_labels"],
                    "app LLM inference; no synthetic training data",
                    "llm",
                )
            )

    if "claude" in model_families:
        claude_frames = claude_predictions(datasets, limit=args.claude_limit)
        for task, frame in claude_frames.items():
            prediction_frames.append(frame)
            summary_rows.append(
                evaluate_frame(
                    task,
                    task,
                    frame,
                    infos[task]["supported_labels"],
                    "inbox-sorter pipeline inference (Anthropic API); no synthetic training data",
                    "claude",
                )
            )

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "review_file": display_path(review_path, REPO_ROOT),
        "taxonomy_sha256_16": tax_digest,
        "task": args.task,
        "tasks": tasks,
        "folds": args.folds,
        "seed": args.seed,
        "model_families": model_families,
        "ml_estimators": {
            "category": "linear_svm",
            "action": "complement_nb_balanced",
        } if "ml" in model_families else None,
        "llm_model": None,
        "claude_model": None,
        "claude_limit": args.claude_limit,
        "label_mapping": {
            "FoS General": "general",
            "Career": "career",
            "Medical": "medical",
            "Promotions": "promotional",
            "Canvas": "canva",
            "Others": "others",
            "Needs a reply": "needs_reply",
            "Needs an action": "needs_action",
            "Reminder": "reminder",
            "No action needed": "no_immediate_action",
            "Further review": "no_immediate_action",
        },
        "encoders": {
            "category": args.encoder_category,
            "action": args.encoder_action,
        },
        "synthetic": display_path(synthetic_path, REPO_ROOT) if syn_data else None,
        "synthetic_tasks": ",".join(sorted(syn_data)) if syn_data else None,
        "rows": {task: len(datasets[task]) for task in tasks},
        "category_rule_rows": infos.get("category", {}).get("rule_rows_excluded"),
        "evaluation_rows": {
            f"{row['model_family']}:{row['dataset']}": int(row["n"])
            for row in summary_rows
        },
        "versions": {
            pkg: package_version(pkg)
            for pkg in ("numpy", "pandas", "scikit-learn", "torch", "transformers")
        },
    }
    if "llm" in model_families:
        from app.config import settings

        manifest["llm_model"] = settings.ollama_model
    if "claude" in model_families:
        from evaluation.performance import _claude_model_name

        manifest["claude_model"] = _claude_model_name()
    write_artifacts(out_dir, summary_rows, prediction_frames, manifest)


if __name__ == "__main__":
    main()
