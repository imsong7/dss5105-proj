"""Find potentially mislabeled rows using cross-validated Cleanlab predictions.

Usage:
    python evaluation/label_audit.py
    python evaluation/label_audit.py --task category --out /tmp/category_audit.csv

The output is a review aid, not an automatic correction to the labels.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODERS_DIR = REPO_ROOT / "text-encoders"
for _path in (REPO_ROOT, ENCODERS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evaluation import display_path  # noqa: E402
from src.data import DEFAULT_ENCODERS, load_review, load_taxonomy, task_dataset  # noqa: E402
from src.model import FrozenEncoder, fit_head  # noqa: E402

DEFAULT_REVIEW = REPO_ROOT / "data" / "labels.csv"
DEFAULT_OUT = REPO_ROOT / "evaluation" / "results" / "label_audit.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", default=str(DEFAULT_REVIEW), help="labeled review CSV")
    parser.add_argument("--task", choices=["both", "category", "action"], default="both")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--encoder-category", default=DEFAULT_ENCODERS["category"])
    parser.add_argument("--encoder-action", default=DEFAULT_ENCODERS["action"])
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="audit CSV output path")
    return parser.parse_args()


def cross_validated_probabilities(
    frame: pd.DataFrame,
    encoder_name: str,
    folds: int,
    seed: int,
    encoder_factory=FrozenEncoder,
) -> tuple[list[str], np.ndarray]:
    """Create one out-of-fold probability vector for each real review row."""
    from sklearn.model_selection import StratifiedKFold

    labels = frame["label_key"].drop_duplicates().tolist()
    targets = frame["label_key"].map(
        {label: i for i, label in enumerate(labels)}
    ).to_numpy()
    counts = np.bincount(targets, minlength=len(labels))
    if folds < 2 or counts.min() < folds:
        raise ValueError(
            f"Need at least {folds} rows in every class for stratified CV; "
            f"class counts: {dict(zip(labels, counts.tolist()))}."
        )

    vectors = encoder_factory(encoder_name).encode(frame["text"].tolist())
    probabilities = np.zeros((len(frame), len(labels)), dtype=float)
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for train_idx, test_idx in splitter.split(vectors, targets):
        classifier = fit_head(vectors[train_idx], targets[train_idx])
        fold_probs = classifier.predict_proba(vectors[test_idx])
        probabilities[np.ix_(test_idx, classifier.classes_.astype(int))] = fold_probs

    if not np.isfinite(probabilities).all() or not np.allclose(
        probabilities.sum(axis=1), 1.0, atol=1e-5
    ):
        raise ValueError("Cross-validated predictions contain invalid probabilities.")
    return labels, probabilities


def audit_frame(
    task: str,
    frame: pd.DataFrame,
    labels: list[str],
    probabilities: np.ndarray,
) -> pd.DataFrame:
    """Return all rows with Cleanlab's suspected-label-issue flag and review order."""
    from cleanlab.filter import find_label_issues

    label_ids = {label: i for i, label in enumerate(labels)}
    targets = frame["label_key"].map(label_ids).to_numpy()
    issues = np.asarray(find_label_issues(
        labels=targets,
        pred_probs=probabilities,
        return_indices_ranked_by="self_confidence",
    ))
    issue_indices = np.flatnonzero(issues) if issues.dtype == bool else issues.astype(int)
    issue_ranks = {int(index): rank for rank, index in enumerate(issue_indices, 1)}
    predictions = probabilities.argmax(axis=1)
    current_probabilities = probabilities[np.arange(len(frame)), targets]
    output = frame[["review_id", "Subject", "From", "Preview"]].copy()
    output.insert(1, "task", task)
    output["current_label"] = frame["label_key"].to_numpy()
    output["suggested_label"] = [labels[index] for index in predictions]
    output["is_suspected_issue"] = [
        index in issue_ranks for index in range(len(frame))
    ]
    output["cleanlab_rank"] = [
        issue_ranks.get(index, pd.NA) for index in range(len(frame))
    ]
    output["current_label_probability"] = current_probabilities
    output["_sort"] = [
        issue_ranks.get(index, len(issue_ranks) + index + 1)
        for index in range(len(frame))
    ]
    return output.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)


def main() -> None:
    try:
        from cleanlab.filter import find_label_issues  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Cleanlab is required. Install project dependencies with "
            "`pip install -r requirements.txt`."
        ) from exc

    args = parse_args()
    taxonomy, _ = load_taxonomy()
    review = load_review(args.review)
    tasks = ["category", "action"] if args.task == "both" else [args.task]
    audit_frames = []
    for task in tasks:
        frame, info = task_dataset(
            review, task, taxonomy[task], allow_missing=True, training=False
        )
        encoder_name = (
            args.encoder_category if task == "category" else args.encoder_action
        )
        labels, probabilities = cross_validated_probabilities(
            frame, encoder_name, args.folds, args.seed
        )
        audited = audit_frame(task, frame, labels, probabilities)
        flagged = audited[audited["is_suspected_issue"]]
        print(
            f"[{task}] reviewed={len(audited)} suspected_issues={len(flagged)} "
            f"rule_excluded={info['rule_rows_excluded']} "
            f"encoder={encoder_name}"
        )
        audit_frames.append(audited)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(audit_frames, ignore_index=True).to_csv(
        out_path, index=False, encoding="utf-8-sig"
    )
    print(f"Dataset: {display_path(args.review, REPO_ROOT)}")
    print(f"Audit: {display_path(str(out_path), REPO_ROOT)}")
    print("Review flagged rows manually; this script does not change dataset labels.")


if __name__ == "__main__":
    main()
