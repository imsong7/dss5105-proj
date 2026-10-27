"""Plot class distributions for the shared email-review dataset.

Usage:
    python evaluation/distribution.py
    python evaluation/distribution.py --review data/labels.csv --out /tmp/labels.png
"""

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODERS_DIR = REPO_ROOT / "text-encoders"
for _path in (REPO_ROOT, ENCODERS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evaluation import display_path  # noqa: E402
from src.data import load_review, load_taxonomy, task_dataset  # noqa: E402

DEFAULT_REVIEW = REPO_ROOT / "data" / "labels.csv"
DEFAULT_OUT = REPO_ROOT / "evaluation" / "results" / "label_distribution.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", default=str(DEFAULT_REVIEW), help="labeled review CSV")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output PNG path")
    return parser.parse_args()


def class_distributions(review_path: str) -> dict[str, dict]:
    """Return counts and proportions after the evaluation workflow's row filtering."""
    labels, _ = load_taxonomy()
    review = load_review(review_path)
    distributions = {}
    for task in ("category", "action"):
        frame, info = task_dataset(
            review, task, labels[task], allow_missing=True, training=False
        )
        counts = frame["label_key"].value_counts()
        class_labels = info["supported_labels"]
        total = len(frame)
        if not total:
            raise ValueError(f"No usable rows for task {task!r}.")
        distributions[task] = {
            "labels": class_labels,
            "counts": [int(counts.get(label, 0)) for label in class_labels],
            "proportions": [float(counts.get(label, 0)) / total for label in class_labels],
            "total": total,
        }
    return distributions


def plot_distribution(distributions: dict[str, dict], path: Path) -> None:
    """Save an evaluation-style two-panel count-and-proportion bar chart."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, task in zip(axes, ("category", "action")):
        data = distributions[task]
        y = np.arange(len(data["labels"]))
        bars = ax.barh(y, data["proportions"])
        ax.set_yticks(y)
        ax.set_yticklabels(data["labels"])
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.set_xlabel("Proportion")
        ax.set_title(f"{task.title()} (n={data['total']})")
        ax.grid(axis="x", alpha=0.25)
        ax.set_axisbelow(True)
        for bar, count, proportion in zip(
            bars, data["counts"], data["proportions"]
        ):
            ax.text(
                min(proportion + 0.015, 0.82),
                bar.get_y() + bar.get_height() / 2,
                f"{count} ({proportion:.1%})",
                va="center",
                fontsize=9,
            )

    fig.suptitle("Evaluation dataset label distribution")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    distributions = class_distributions(args.review)
    out_path = Path(args.out)
    plot_distribution(distributions, out_path)
    print(f"Dataset: {display_path(args.review, REPO_ROOT)}")
    for task, data in distributions.items():
        counts = dict(zip(data["labels"], data["counts"]))
        proportions = {
            label: f"{proportion:.6%}"
            for label, proportion in zip(data["labels"], data["proportions"])
        }
        print(f"{task}: n={data['total']} counts={counts} proportions={proportions}")
    print(f"Plot: {display_path(str(out_path), REPO_ROOT)}")


if __name__ == "__main__":
    main()
