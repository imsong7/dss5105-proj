"""Tests for the shared model-comparison runner."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from evaluation.compare_models import (
    evaluate,
    load_dataset,
    score_predictions,
)


class StaticClassifier:
    def __init__(self, category, action):
        self.category = category
        self.action = action
        self.seen = []

    def classify(self, email):
        self.seen.append(email.id)
        return {
            "content_category": self.category,
            "reply_nature": self.action,
            "deadline": None,
            "reason": "test",
        }


class FailingClassifier:
    def classify(self, email):
        raise RuntimeError("failure")


def make_cli_adapter():
    return StaticClassifier("general", "needs_action")


class CompareModelsTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame([
            {
                "email_id": "one",
                "Subject": "Subject one",
                "From": "student@example.com",
                "Preview": "Preview one",
                "Body": "Full body one",
                "gold_category": "general",
                "gold_action": "needs_action",
            },
            {
                "email_id": "two",
                "Subject": "Canvas alert",
                "From": "Canvas <notifications@instructure.com>",
                "Preview": "Preview two",
                "Body": "",
                "gold_category": "canva",
                "gold_action": "reminder",
            },
        ])

    def test_load_dataset_supports_existing_review_columns_and_skip_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            self.frame.rename(columns={
                "email_id": "review_id",
                "gold_category": "category",
                "gold_action": "action",
            }).assign(category=["general", "__skip__"]).to_csv(path, index=False)

            loaded = load_dataset(path)

        self.assertEqual(loaded["email_id"].tolist(), ["one", "two"])
        self.assertEqual(loaded["gold_category"].tolist(), ["general", "__skip__"])

    def test_models_receive_same_emails_and_rule_applies_consistently(self):
        first = StaticClassifier("others", "needs_action")
        second = StaticClassifier("medical", "reminder")
        predictions = evaluate(
            self.frame,
            [("first", lambda: first), ("second", lambda: second)],
        )

        self.assertEqual(first.seen, ["one", "two"])
        self.assertEqual(second.seen, ["one", "two"])
        canvas = predictions[predictions["email_id"] == "two"]
        self.assertEqual(canvas["pred_category"].tolist(), ["canva", "canva"])
        self.assertTrue(canvas["rule_applied"].all())
        self.assertEqual(canvas["pred_action"].tolist(), ["needs_action", "reminder"])

    def test_metrics_include_task_scores_paired_exact_match_and_operations(self):
        classifier = StaticClassifier("general", "needs_action")
        predictions = evaluate(self.frame, [("baseline", lambda: classifier)])
        summary, per_class = score_predictions(predictions, bootstrap=20, seed=1)

        tasks = set(summary["task"])
        self.assertEqual(tasks, {"category", "action", "both_exact_match", "operations"})
        category = summary[summary["task"] == "category"].iloc[0]
        self.assertEqual(category["accuracy"], 1.0)
        self.assertTrue({"precision", "recall", "f1", "support"} <= set(per_class.columns))
        self.assertTrue(summary.loc[summary["task"] == "operations", "median_latency_ms"].notna().all())

    def test_errors_are_kept_as_invalid_predictions(self):
        predictions = evaluate(self.frame, [("broken", FailingClassifier)])
        summary, _ = score_predictions(predictions, bootstrap=20, seed=1)
        ops = summary[summary["task"] == "operations"].iloc[0]

        self.assertTrue((predictions["pred_category"] == "__invalid__").all())
        self.assertEqual(ops["error_rate"], 1.0)
        self.assertEqual(ops["invalid_action_rate"], 1.0)

    def test_cli_writes_results_with_an_adapter_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "labels.csv"
            output = root / "results"
            self.frame.rename(columns={
                "gold_category": "category",
                "gold_action": "action",
            }).to_csv(dataset, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    "evaluation/compare_models.py",
                    "--dataset",
                    str(dataset),
                    "--adapter",
                    "fake=evaluation.test_compare_models:make_cli_adapter",
                    "--bootstrap",
                    "5",
                    "--out-dir",
                    str(output),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"predictions.csv", "summary.csv", "per_class.csv", "manifest.json"},
            )
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["models"], ["fake"])
            self.assertNotIn("Full body one", (output / "predictions.csv").read_text())


if __name__ == "__main__":
    unittest.main()
