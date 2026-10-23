"""Unit tests for the offline evaluator.

These do not download or load encoders. Run from the repo root:

    .venv/bin/python -m unittest evaluation.test_offline_f1
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.offline_f1 import (  # noqa: E402
    bootstrap_metrics,
    bootstrap_rate,
    category_end_to_end,
    evaluate_frame,
)


class BootstrapTests(unittest.TestCase):
    def test_perfect_predictions_have_unit_ci(self) -> None:
        y = np.array(["a", "a", "b", "b", "c"])
        acc_ci, f1_ci = bootstrap_metrics(y, y, ["a", "b", "c"], n_boot=50, seed=1)
        self.assertEqual(acc_ci, (1.0, 1.0))
        self.assertEqual(f1_ci, (1.0, 1.0))

    def test_ci_brackets_point_estimates(self) -> None:
        y = np.array(["a", "a", "b", "b", "c", "c", "c"])
        pred = np.array(["a", "b", "b", "b", "c", "a", "c"])
        acc_ci, f1_ci = bootstrap_metrics(y, pred, ["a", "b", "c"], n_boot=200, seed=7)
        point_acc = float((y == pred).mean())
        self.assertLessEqual(acc_ci[0], point_acc)
        self.assertGreaterEqual(acc_ci[1], point_acc)
        self.assertLessEqual(f1_ci[0], f1_ci[1])

    def test_rate_ci(self) -> None:
        self.assertEqual(bootstrap_rate(np.ones(10, dtype=bool), 100, 3), (1.0, 1.0))
        self.assertEqual(bootstrap_rate(np.zeros(10, dtype=bool), 100, 3), (0.0, 0.0))


class EndToEndTests(unittest.TestCase):
    def test_rule_and_model_rows(self) -> None:
        review = pd.DataFrame(
            [
                {
                    "review_id": "rule1",
                    "Subject": "Canvas invite",
                    "From": "Notifications <notifications@instructure.com>",
                    "Preview": "A shared design",
                    "category": "canva",
                },
                {
                    "review_id": "model1",
                    "Subject": "Clinic appointment",
                    "From": "clinic@example.com",
                    "Preview": "Your appointment is tomorrow",
                    "category": "medical",
                },
            ]
        )
        oof = pd.DataFrame(
            [
                {
                    "review_id": "model1",
                    "pred_label": "medical",
                    "confidence": 0.9,
                    "fold": 1,
                }
            ]
        )
        out = category_end_to_end(review, oof, ["medical", "canva"])
        self.assertEqual(len(out), 2)
        rule = out.loc[out["review_id"] == "rule1"].iloc[0]
        model = out.loc[out["review_id"] == "model1"].iloc[0]
        self.assertEqual((rule["pred_label"], rule["source"]), ("canva", "rule"))
        self.assertEqual((model["pred_label"], model["source"]), ("medical", "model"))

    def test_missing_oof_prediction_fails(self) -> None:
        review = pd.DataFrame(
            [
                {
                    "review_id": "model1",
                    "Subject": "Clinic appointment",
                    "From": "clinic@example.com",
                    "Preview": "Your appointment is tomorrow",
                    "category": "medical",
                }
            ]
        )
        oof = pd.DataFrame(columns=["review_id", "pred_label", "confidence", "fold"])
        with self.assertRaises(SystemExit):
            category_end_to_end(review, oof, ["medical"])


class EvaluateFrameTests(unittest.TestCase):
    def test_summary_and_per_class_rows(self) -> None:
        frame = pd.DataFrame(
            {
                "true_label": ["a", "a", "b", "b"],
                "pred_label": ["a", "b", "b", "b"],
            }
        )
        summary, per_class, confusion = evaluate_frame(
            "toy", "task", frame, ["a", "b"], n_boot=50, seed=1
        )
        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["accuracy"], 0.75)
        self.assertAlmostEqual(summary["macro_f1"], 0.7333333333333334)
        self.assertEqual(len(per_class), 2)
        self.assertEqual(len(confusion), 4)
        self.assertEqual(summary["dataset"], "toy")


if __name__ == "__main__":
    unittest.main()
