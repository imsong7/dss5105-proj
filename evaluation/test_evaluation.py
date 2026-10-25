"""Unit tests for the evaluation suite.

These do not load torch, transformers, or the trained heads, and they do not
call Llama, Ollama, or BERT. Run from the repo root:

    .venv/bin/python -m unittest evaluation.test_evaluation -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
EMAIL_DIR = REPO_ROOT / "email-sorter"
for _path in (REPO_ROOT, EMAIL_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.bert_classifier import BertClassifier, _model_text  # noqa: E402
from app.models import Email  # noqa: E402
from evaluation import bootstrap_proportion  # noqa: E402
from evaluation.offline_f1 import (  # noqa: E402
    bootstrap_metrics,
    category_end_to_end,
    evaluate_frame,
)
from evaluation.operational_benchmark import (  # noqa: E402
    CallRecord,
    _agreement,
    _llama_raw_status,
    render_report,
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
        point, lo, hi = bootstrap_proportion(np.ones(10, dtype=bool), 100, 3)
        self.assertEqual((point, lo, hi), (1.0, 1.0, 1.0))
        point, lo, hi = bootstrap_proportion(np.zeros(10, dtype=bool), 100, 3)
        self.assertEqual((point, lo, hi), (0.0, 0.0, 0.0))


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
    def test_summary_row(self) -> None:
        frame = pd.DataFrame(
            {
                "true_label": ["a", "a", "b", "b"],
                "pred_label": ["a", "b", "b", "b"],
            }
        )
        summary = evaluate_frame("toy", "task", frame, ["a", "b"], n_boot=50, seed=1)
        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["accuracy"], 0.75)
        self.assertAlmostEqual(summary["macro_f1"], 0.7333333333333334)
        self.assertEqual(summary["dataset"], "toy")


def _raw(content: str):
    return SimpleNamespace(content=content)


def _record(
    review_id: str,
    phase: str,
    run: int,
    category: str,
    action: str,
    mode: str = "full",
) -> CallRecord:
    return CallRecord(
        backend="llama",
        review_id=review_id,
        phase=phase,
        run=run,
        input_mode=mode,
        input_chars=100,
        latency_ms=1.0,
        category=category,
        action=action,
        raw_valid=True,
        invalid_reason=None,
        input_tokens=10,
        output_tokens=5,
        server_load_ms=None,
        true_action="",
        true_category="",
        raw_excerpt="",
    )


class RawStatusTests(unittest.TestCase):
    def test_valid_json_and_labels(self) -> None:
        result = {
            "raw": _raw('{"content_category": "medical", "reply_nature": "reminder"}'),
            "parsed": object(),
            "parsing_error": None,
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertTrue(valid)
        self.assertIsNone(reason)

    def test_invalid_label(self) -> None:
        result = {
            "raw": _raw('{"content_category": "Medical?", "reply_nature": "reminder"}'),
            "parsed": object(),
            "parsing_error": None,
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertIn("invalid_category", reason or "")

    def test_non_json(self) -> None:
        result = {"raw": _raw("not json"), "parsed": object(), "parsing_error": None}
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertEqual(reason, "raw_not_json")

    def test_parsing_error(self) -> None:
        result = {
            "raw": _raw("{}"),
            "parsed": None,
            "parsing_error": "bad schema",
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertIn("parsing_error", reason or "")


class AgreementTests(unittest.TestCase):
    def test_bootstrap_bounds(self) -> None:
        point, lo, hi = bootstrap_proportion([True, True, False], 200, 7)
        self.assertAlmostEqual(point, 2 / 3)
        self.assertLessEqual(lo, point)
        self.assertGreaterEqual(hi, point)

    def test_consistency_and_length(self) -> None:
        records = [
            _record("a", "main", 1, "medical", "reminder"),
            _record("a", "main", 2, "medical", "reminder"),
            _record("a", "length_short", 0, "medical", "reminder", "short"),
            _record("b", "main", 1, "medical", "reminder"),
            _record("b", "main", 2, "medical", "needs_reply"),
            _record("b", "length_short", 0, "medical", "needs_action", "short"),
        ]
        args = SimpleNamespace(runs=2)
        consistency, length = _agreement(records, args)
        self.assertEqual(consistency, [True, False])
        self.assertEqual(length, [True, False])


class ReportTests(unittest.TestCase):
    def test_nan_error_cell_is_not_an_error(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "backend": "bert",
                    "error": float("nan"),
                    "sample_n": 1,
                    "load_ms": 100.0,
                    "cold_call_ms": 10.0,
                    "warm_p50_ms": 5.0,
                    "warm_p95_ms": 6.0,
                    "peak_total_mb": 500.0,
                    "model_size_mb": 100.0,
                    "input_tokens_mean": 10.0,
                    "output_tokens_mean": 0.0,
                    "energy_kwh": 0.0001,
                    "invalid_format_rate": None,
                    "consistency_exact": 1.0,
                    "length_both": 1.0,
                }
            ]
        )
        manifest = {
            "sample_n": 1,
            "total_rows": 1,
            "runs": 5,
            "seed": 42,
            "body_char_limit": 3000,
            "short_chars": 200,
            "sample_action_counts": {},
        }
        report = render_report(summary, manifest)
        self.assertNotIn("ERROR", report)
        self.assertIn("bert", report)


class FakePredictor:
    def __init__(self, label: str):
        self.label = label
        self.calls: list[tuple[str, str, str]] = []

    def predict(self, subject: str, body: str, from_addr: str = ""):
        self.calls.append((subject, body, from_addr))
        return self.label, 0.9


def _classifier() -> BertClassifier:
    clf = object.__new__(BertClassifier)
    clf._load_error = None
    clf._category_clf = FakePredictor("medical")
    clf._action_clf = FakePredictor("reminder")
    return clf


def _email(body: str, preview: str) -> Email:
    return Email(
        id="1",
        subject="Clinic appointment",
        sender="clinic@example.com",
        preview=preview,
        body=body,
    )


class ModelTextTests(unittest.TestCase):
    def test_body_is_preferred(self) -> None:
        self.assertEqual(_model_text(_email("full body", "short preview")), "full body")

    def test_preview_is_used_when_body_is_empty(self) -> None:
        self.assertEqual(_model_text(_email("", "short preview")), "short preview")

    def test_whitespace_body_falls_back_to_preview(self) -> None:
        self.assertEqual(_model_text(_email("   \n", "short preview")), "short preview")

    def test_both_empty(self) -> None:
        self.assertEqual(_model_text(_email("", "")), "")


class AvailabilityTests(unittest.TestCase):
    def test_both_heads_are_required(self) -> None:
        clf = _classifier()
        self.assertTrue(clf.available)
        clf._action_clf = None
        self.assertFalse(clf.available)

    def test_load_error_blocks_classification(self) -> None:
        clf = _classifier()
        clf._load_error = "missing action head"
        with self.assertRaises(RuntimeError):
            clf.classify(_email("full body", "short preview"))


class ClassifyInputTests(unittest.TestCase):
    def test_both_heads_receive_the_body(self) -> None:
        clf = _classifier()
        result = clf.classify(_email("full body", "short preview"))

        self.assertEqual(result.content_category, "medical")
        self.assertEqual(result.reply_nature, "reminder")
        expected = [("Clinic appointment", "full body", "clinic@example.com")]
        self.assertEqual(clf._category_clf.calls, expected)
        self.assertEqual(clf._action_clf.calls, expected)

    def test_both_heads_receive_preview_when_body_is_empty(self) -> None:
        clf = _classifier()
        clf.classify(_email("", "short preview"))

        expected = [("Clinic appointment", "short preview", "clinic@example.com")]
        self.assertEqual(clf._category_clf.calls, expected)
        self.assertEqual(clf._action_clf.calls, expected)


if __name__ == "__main__":
    unittest.main()
