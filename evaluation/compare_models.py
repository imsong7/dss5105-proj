"""Compare email classifiers on the same labeled emails.

Run from the repository root:
    .venv/bin/python evaluation/compare_models.py --model llama --model bert
    .venv/bin/python evaluation/compare_models.py --adapter agent=package.module:factory
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import math
import statistics
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
EMAIL_SORTER_DIR = REPO_ROOT / "email-sorter"
for import_path in (REPO_ROOT, EMAIL_SORTER_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from app.models import Email  # noqa: E402
from app.rules import category_by_rule  # noqa: E402
from app.taxonomy import CONTENT_CATEGORIES, REPLY_NATURE  # noqa: E402
from evaluation import write_csv, write_json  # noqa: E402

DEFAULT_DATASET = REPO_ROOT / "bert" / "data" / "labels.csv"
DEFAULT_OUT = REPO_ROOT / "evaluation" / "results" / "model_comparison"
SKIP = "__skip__"
INVALID = "__invalid__"
TASKS = {
    "category": ("gold_category", "content_category", "pred_category", CONTENT_CATEGORIES),
    "action": ("gold_action", "reply_nature", "pred_action", REPLY_NATURE),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Labeled CSV")
    parser.add_argument(
        "--model",
        action="append",
        choices=("llama", "bert"),
        help="Built-in model to evaluate; repeat to select multiple (default: llama and bert)",
    )
    parser.add_argument(
        "--adapter",
        action="append",
        default=[],
        metavar="NAME=MODULE:FACTORY",
        help="Add a future model adapter that returns an object with classify(email)",
    )
    parser.add_argument("--split", help="Optional split column value, e.g. test")
    parser.add_argument(
        "--rule-policy",
        choices=("app", "none"),
        default="app",
        help="Apply the app's sender-category rules to every model, or evaluate models alone",
    )
    parser.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap samples for 95%% CIs")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    return parser.parse_args()


def _clean_label(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def load_dataset(path: str | Path, split: str | None = None) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Dataset does not exist: {path}")

    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    id_col = "review_id" if "review_id" in frame.columns else "email_id"
    required = {id_col, "category", "action"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Dataset is missing required columns: {', '.join(missing)}")
    text_columns = {"Subject", "subject", "Preview", "preview", "Body", "body"}
    if not text_columns.intersection(frame.columns):
        raise ValueError("Dataset must include a subject, preview, or body column")
    if frame[id_col].str.strip().eq("").any():
        raise ValueError("Dataset contains an empty email ID")
    if frame[id_col].duplicated().any():
        raise ValueError("Dataset contains duplicate email IDs")
    if split is not None:
        if "split" not in frame.columns:
            raise ValueError("--split requires a 'split' column in the dataset")
        frame = frame[frame["split"].str.strip() == split].copy()

    frame = frame.rename(columns={id_col: "email_id", "category": "gold_category", "action": "gold_action"})
    for task, (gold_col, _, _, taxonomy) in TASKS.items():
        frame[gold_col] = frame[gold_col].map(_clean_label)
        bad = sorted(set(frame[gold_col]) - set(taxonomy) - {SKIP, ""})
        if bad:
            raise ValueError(f"Invalid {task} labels: {bad}; expected keys from the app taxonomy")
    frame = frame[
        frame["gold_category"].ne("") | frame["gold_action"].ne("")
    ].reset_index(drop=True)
    if frame.empty:
        raise ValueError("Dataset has no reviewed rows for the selected split")
    return frame


def _as_mapping(result: object) -> Mapping:
    if isinstance(result, Mapping):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    fields = ("content_category", "reply_nature", "deadline", "reason")
    if all(hasattr(result, field) for field in fields):
        return {field: getattr(result, field) for field in fields}
    raise TypeError("Adapter output must be a mapping or a classification model")


def _valid_prediction(value: object, taxonomy: Mapping) -> tuple[str, bool]:
    label = _clean_label(value)
    return (label, True) if label in taxonomy else (INVALID, False)


def _adapter_spec(value: str) -> tuple[str, str, str]:
    if "=" not in value:
        raise ValueError(f"Invalid adapter '{value}'; expected NAME=MODULE:FACTORY")
    name, target = value.split("=", 1)
    module, separator, factory = target.partition(":")
    if not name.strip() or not separator or not module or not factory:
        raise ValueError(f"Invalid adapter '{value}'; expected NAME=MODULE:FACTORY")
    return name.strip(), module, factory


def load_adapters(models: list[str], specs: list[str]) -> list[tuple[str, Callable[[], object]]]:
    from app.classifier_base import create_classifier

    adapters = [(name, lambda name=name: create_classifier(name)) for name in models]
    names = set(models)
    for spec in specs:
        name, module_name, factory_name = _adapter_spec(spec)
        if name in names:
            raise ValueError(f"Duplicate model name: {name}")
        factory = getattr(importlib.import_module(module_name), factory_name)
        if not callable(factory):
            raise ValueError(f"Adapter factory is not callable: {spec}")
        adapters.append((name, factory))
        names.add(name)
    if not adapters:
        raise ValueError("Select at least one model or adapter")
    return adapters


def _email(row: pd.Series) -> Email:
    preview = str(row.get("Preview", row.get("preview", "")) or "")
    body = str(row.get("Body", row.get("body", "")) or "")
    return Email(
        id=str(row["email_id"]),
        subject=str(row.get("Subject", row.get("subject", "")) or ""),
        sender=str(row.get("From", row.get("sender", "")) or ""),
        received=str(row.get("Received DateTime", row.get("received", "")) or ""),
        preview=preview,
        body=body,
    )


def evaluate(
    frame: pd.DataFrame,
    adapters: list[tuple[str, Callable[[], object]]],
    *,
    rule_policy: str = "app",
) -> pd.DataFrame:
    records = []
    for name, factory in adapters:
        model = factory()
        classify = getattr(model, "classify", None)
        if not callable(classify):
            raise TypeError(f"Adapter '{name}' must expose classify(email)")

        for _, row in frame.iterrows():
            email = _email(row)
            started = time.perf_counter()
            error = ""
            category, category_valid = INVALID, False
            action, action_valid = INVALID, False
            deadline = None
            rule_applied = False
            try:
                result = _as_mapping(classify(email))
                category, category_valid = _valid_prediction(
                    result.get("content_category"), CONTENT_CATEGORIES
                )
                action, action_valid = _valid_prediction(
                    result.get("reply_nature"), REPLY_NATURE
                )
                deadline = result.get("deadline")
                if rule_policy == "app":
                    rule_category = category_by_rule(email.sender)
                    if rule_category:
                        category, category_valid = rule_category, True
                        rule_applied = True
            except Exception as exc:
                error = type(exc).__name__

            records.append(
                {
                    "email_id": email.id,
                    "model": name,
                    "gold_category": row["gold_category"],
                    "pred_category": category,
                    "category_valid": category_valid,
                    "gold_action": row["gold_action"],
                    "pred_action": action,
                    "action_valid": action_valid,
                    "deadline": deadline,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "rule_applied": rule_applied,
                    "error": error,
                }
            )
    return pd.DataFrame(records)


def _bootstrap_ci(y_true: np.ndarray, y_pred: np.ndarray, labels: list[str], seed: int, n_boot: int) -> dict:
    from sklearn.metrics import accuracy_score, f1_score

    groups = [np.flatnonzero(y_true == label) for label in np.unique(y_true)]
    rng = np.random.default_rng(seed)
    accuracy = np.empty(n_boot)
    macro_f1 = np.empty(n_boot)
    for index in range(n_boot):
        sample = np.concatenate([
            rng.choice(group, size=len(group), replace=True) for group in groups
        ])
        accuracy[index] = accuracy_score(y_true[sample], y_pred[sample])
        macro_f1[index] = f1_score(
            y_true[sample], y_pred[sample], labels=labels, average="macro", zero_division=0
        )
    return {
        "accuracy_ci_low": float(np.percentile(accuracy, 2.5)),
        "accuracy_ci_high": float(np.percentile(accuracy, 97.5)),
        "macro_f1_ci_low": float(np.percentile(macro_f1, 2.5)),
        "macro_f1_ci_high": float(np.percentile(macro_f1, 97.5)),
    }


def score_predictions(
    predictions: pd.DataFrame, *, bootstrap: int = 2000, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame]:
    from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support

    summaries = []
    per_class = []
    for model_name, model_rows in predictions.groupby("model", sort=False):
        for offset, (task, (gold_col, _, pred_col, taxonomy)) in enumerate(TASKS.items()):
            rows = model_rows[model_rows[gold_col].ne("") & model_rows[gold_col].ne(SKIP)]
            if rows.empty:
                continue
            y_true = rows[gold_col].to_numpy()
            y_pred = rows[pred_col].to_numpy()
            labels = list(taxonomy)
            p, r, f, support = precision_recall_fscore_support(
                y_true, y_pred, labels=labels, zero_division=0
            )
            for label, precision, recall, f1, count in zip(labels, p, r, f, support):
                per_class.append({
                    "model": model_name,
                    "task": task,
                    "label": label,
                    "precision": float(precision),
                    "recall": float(recall),
                    "f1": float(f1),
                    "support": int(count),
                })
            macro_f1 = f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
            ci = _bootstrap_ci(y_true, y_pred, labels, seed + offset, bootstrap)
            summaries.append({
                "model": model_name,
                "task": task,
                "n": len(rows),
                "accuracy": float(accuracy_score(y_true, y_pred)),
                "macro_f1": float(macro_f1),
                "macro_precision": float(precision_recall_fscore_support(
                    y_true, y_pred, labels=labels, average="macro", zero_division=0
                )[0]),
                "macro_recall": float(precision_recall_fscore_support(
                    y_true, y_pred, labels=labels, average="macro", zero_division=0
                )[1]),
                **ci,
            })

        paired = model_rows[
            model_rows["gold_category"].ne("")
            & model_rows["gold_category"].ne(SKIP)
            & model_rows["gold_action"].ne("")
            & model_rows["gold_action"].ne(SKIP)
        ]
        if not paired.empty:
            exact = (
                paired["gold_category"].eq(paired["pred_category"])
                & paired["gold_action"].eq(paired["pred_action"])
            )
            point = float(exact.mean())
            rng = np.random.default_rng(seed + 99)
            values = exact.to_numpy(dtype=float)
            samples = np.array([
                rng.choice(values, size=len(values), replace=True).mean()
                for _ in range(bootstrap)
            ])
            summaries.append({
                "model": model_name,
                "task": "both_exact_match",
                "n": len(paired),
                "accuracy": point,
                "macro_f1": math.nan,
                "macro_precision": math.nan,
                "macro_recall": math.nan,
                "accuracy_ci_low": float(np.percentile(samples, 2.5)),
                "accuracy_ci_high": float(np.percentile(samples, 97.5)),
                "macro_f1_ci_low": math.nan,
                "macro_f1_ci_high": math.nan,
            })

        latencies = model_rows["latency_ms"].to_numpy()
        summaries.append({
            "model": model_name,
            "task": "operations",
            "n": len(model_rows),
            "accuracy": math.nan,
            "macro_f1": math.nan,
            "macro_precision": math.nan,
            "macro_recall": math.nan,
            "median_latency_ms": float(statistics.median(latencies)),
            "p95_latency_ms": float(np.percentile(latencies, 95)),
            "error_rate": float(model_rows["error"].ne("").mean()),
            "invalid_category_rate": float((~model_rows["category_valid"]).mean()),
            "invalid_action_rate": float((~model_rows["action_valid"]).mean()),
        })

    return pd.DataFrame(summaries), pd.DataFrame(per_class)


def main() -> int:
    args = parse_args()
    if args.bootstrap < 1:
        raise SystemExit("--bootstrap must be at least 1")

    try:
        frame = load_dataset(args.dataset, args.split)
        models = args.model if args.model is not None else ([] if args.adapter else ["llama", "bert"])
        adapters = load_adapters(models, args.adapter)
    except (ImportError, AttributeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    predictions = evaluate(frame, adapters, rule_policy=args.rule_policy)
    summary, per_class = score_predictions(
        predictions, bootstrap=args.bootstrap, seed=args.seed
    )

    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(predictions, output_dir / "predictions.csv")
    write_csv(summary, output_dir / "summary.csv")
    write_csv(per_class, output_dir / "per_class.csv")
    dataset_path = Path(args.dataset)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "split": args.split,
        "rows": int(len(frame)),
        "models": [name for name, _ in adapters],
        "rule_policy": args.rule_policy,
        "rule_overrides": int(predictions["rule_applied"].sum()),
        "bootstrap_samples": args.bootstrap,
        "seed": args.seed,
        "input_fields": ["subject", "sender", "received", "preview", "body"],
        "notes": "Predictions contain IDs and labels but not email text; keep artifacts private.",
    }
    write_json(manifest, output_dir / "manifest.json")
    print(f"Evaluated {len(adapters)} model(s) on {len(frame)} shared email(s).")
    print(f"Results: {output_dir}")
    if not summary.empty:
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
