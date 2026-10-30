"""Unit tests for the evaluation suite.

Run from the repo root:
    .venv/bin/python -m unittest evaluation.test_evaluation -v
"""

import sys
import tempfile
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

from app.encoder_classifier import EncoderClassifier, _model_text  # noqa: E402
from app.schemas import Email  # noqa: E402
from evaluation import bootstrap_proportion  # noqa: E402
from evaluation.quality import (  # noqa: E402
    bootstrap_metrics,
    both_summary,
    evaluate_frame,
    inference_predictions,
    llm_predictions,
    plot_offline_quality,
    selected_model_families,
)
from evaluation.performance import (  # noqa: E402
    CallRecord,
    _agreement,
    _llama_raw_status,
    plot_operational_performance,
    render_report,
    selected_models,
)
from evaluation.label_audit import (  # noqa: E402
    audit_frame,
    cross_validated_probabilities,
)


class BootstrapTests(unittest.TestCase):
    def test_perfect_predictions_have_unit_ci(self):
        y = np.array(["a", "a", "b", "b", "c"])
        acc_ci, f1_ci = bootstrap_metrics(y, y, ["a", "b", "c"], n_boot=50, seed=1)
        self.assertEqual(acc_ci, (1.0, 1.0))
        self.assertEqual(f1_ci, (1.0, 1.0))

    def test_ci_brackets_point_estimates(self):
        y = np.array(["a", "a", "b", "b", "c", "c", "c"])
        pred = np.array(["a", "b", "b", "b", "c", "a", "c"])
        acc_ci, f1_ci = bootstrap_metrics(y, pred, ["a", "b", "c"], n_boot=200, seed=7)
        point_acc = float((y == pred).mean())
        self.assertLessEqual(acc_ci[0], point_acc)
        self.assertGreaterEqual(acc_ci[1], point_acc)
        self.assertLessEqual(f1_ci[0], f1_ci[1])

    def test_rate_ci(self):
        point, lo, hi = bootstrap_proportion(np.ones(10, dtype=bool), 100, 3)
        self.assertEqual((point, lo, hi), (1.0, 1.0, 1.0))
        point, lo, hi = bootstrap_proportion(np.zeros(10, dtype=bool), 100, 3)
        self.assertEqual((point, lo, hi), (0.0, 0.0, 0.0))


class BothLabelsTests(unittest.TestCase):
    def test_exact_match_uses_classifier_only_category_rows(self):
        category = pd.DataFrame(
            [
                {"review_id": "a", "true_label": "general", "pred_label": "general"},
                {"review_id": "b", "true_label": "career", "pred_label": "general"},
            ]
        )
        action = pd.DataFrame(
            [
                {"review_id": "a", "true_label": "reminder", "pred_label": "reminder"},
                {"review_id": "b", "true_label": "needs_reply", "pred_label": "needs_reply"},
                {"review_id": "canvas", "true_label": "reminder", "pred_label": "reminder"},
            ]
        )
        args = SimpleNamespace(bootstrap=100, seed=3)

        rows = both_summary(
            {
                "encoder:category": category,
                "encoder:action": action,
            },
            args,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dataset"], "both")
        self.assertEqual(rows[0]["n"], 2)
        self.assertAlmostEqual(rows[0]["accuracy"], 0.5)


class LlmPredictionTests(unittest.TestCase):
    def test_one_inference_per_unique_email_and_task_specific_labels(self):
        shared = {
            "review_id": "a",
            "Subject": "Clinic",
            "From": "clinic@example.com",
            "Preview": "Appointment notice",
            "Received DateTime": "2026-01-01",
        }
        category = pd.DataFrame(
            [{**shared, "label_key": "medical"}]
        )
        action = pd.DataFrame(
            [
                {**shared, "label_key": "reminder"},
                {
                    **{**shared, "review_id": "b", "Subject": "Course update"},
                    "label_key": "no_immediate_action",
                },
            ]
        )

        class Predictor:
            def __init__(self):
                self.emails = []

            def classify(self, email):
                self.emails.append(email)
                return SimpleNamespace(
                    content_category="medical",
                    reply_nature="reminder",
                )

        predictor = Predictor()
        frames = llm_predictions(
            {"category": category, "action": action},
            predictor,
        )

        self.assertEqual([email.id for email in predictor.emails], ["a", "b"])
        self.assertEqual(frames["category"]["pred_label"].tolist(), ["medical"])
        self.assertEqual(
            frames["action"]["pred_label"].tolist(),
            ["reminder", "reminder"],
        )
        self.assertTrue(frames["action"]["fold"].isna().all())
        self.assertTrue((frames["action"]["model_family"] == "llm").all())


class ClaudePredictionTests(unittest.TestCase):
    def test_claude_shape_and_limit(self):
        shared = {
            "review_id": "a",
            "Subject": "Clinic",
            "From": "clinic@example.com",
            "Preview": "Appointment notice",
            "Received DateTime": "2026-01-01",
        }
        category = pd.DataFrame([{**shared, "label_key": "medical"}])
        action = pd.DataFrame(
            [
                {**shared, "label_key": "reminder"},
                {**shared, "review_id": "b", "label_key": "reminder"},
            ]
        )

        class Predictor:
            def __init__(self):
                self.emails = []

            def classify(self, email):
                self.emails.append(email)
                return SimpleNamespace(category="medical", action="reminder")

        predictor = Predictor()
        frames = inference_predictions(
            {"category": category, "action": action},
            predictor,
            "claude",
            limit=1,
        )

        self.assertEqual([email.id for email in predictor.emails], ["a"])
        self.assertEqual(frames["category"]["pred_label"].tolist(), ["medical"])
        self.assertEqual(frames["action"]["pred_label"].tolist(), ["reminder"])
        self.assertTrue((frames["action"]["model_family"] == "claude").all())


class ModelFamilySelectionTests(unittest.TestCase):
    def test_model_families(self):
        self.assertEqual(selected_model_families("both"), ["encoder", "ml"])
        self.assertEqual(
            selected_model_families("all"), ["encoder", "ml", "llm", "claude"]
        )
        self.assertEqual(selected_model_families("llm"), ["llm"])
        self.assertEqual(selected_model_families("claude"), ["claude"])


class EvaluateFrameTests(unittest.TestCase):
    def test_summary_row(self):
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


class LabelAuditTests(unittest.TestCase):
    def test_oof_probabilities_are_valid_and_cover_every_row(self):
        frame = pd.DataFrame(
            {
                "text": [f"example {label} {i}" for label in ("a", "b") for i in range(6)],
                "label_key": ["a"] * 6 + ["b"] * 6,
            }
        )

        class Encoder:
            def __init__(self, _name):
                pass

            def encode(self, texts):
                return np.array(
                    [[float("a" in text), float("b" in text)] for text in texts]
                )

        labels, probabilities = cross_validated_probabilities(
            frame, "test", 3, 42, encoder_factory=Encoder
        )

        self.assertEqual(labels, ["a", "b"])
        self.assertEqual(probabilities.shape, (12, 2))
        np.testing.assert_allclose(probabilities.sum(axis=1), 1.0)

    def test_audit_marks_and_ranks_rows_without_changing_labels(self):
        frame = pd.DataFrame(
            {
                "review_id": ["a", "b", "c", "d", "e", "f"],
                "Subject": ["s"] * 6,
                "From": ["f"] * 6,
                "Preview": ["p"] * 6,
                "label_key": ["a", "a", "a", "b", "b", "b"],
            }
        )
        probabilities = np.array(
            [
                [0.95, 0.05],
                [0.95, 0.05],
                [0.05, 0.95],
                [0.05, 0.95],
                [0.05, 0.95],
                [0.05, 0.95],
            ]
        )

        audited = audit_frame("category", frame, ["a", "b"], probabilities)

        self.assertEqual(set(audited["current_label"]), {"a", "b"})
        self.assertTrue(audited["is_suspected_issue"].any())
        self.assertTrue(audited.iloc[0]["is_suspected_issue"])
        self.assertEqual(audited.iloc[0]["cleanlab_rank"], 1)
        self.assertEqual(
            audited.loc[audited["review_id"] == "c", "suggested_label"].item(),
            "b",
        )


class EvaluationPlotTests(unittest.TestCase):
    def test_offline_quality_plot_includes_metrics_and_confidence_intervals(self):
        summary = pd.DataFrame(
            [
                {
                    "dataset": "action",
                    "model_family": family,
                    "accuracy": accuracy,
                    "accuracy_ci_low": accuracy - 0.1,
                    "accuracy_ci_high": accuracy + 0.1,
                    "macro_f1": f1,
                    "macro_f1_ci_low": f1 - 0.1,
                    "macro_f1_ci_high": f1 + 0.1,
                }
                for family, accuracy, f1 in (
                    ("encoder", 0.8, 0.7),
                    ("ml", 0.75, 0.65),
                    ("llm", 0.7, 0.6),
                    ("claude", 0.85, 0.75),
                )
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quality.png"
            plot_offline_quality(summary, path)
            self.assertGreater(path.stat().st_size, 0)

    def test_operational_plot_handles_failed_models(self):
        summary = pd.DataFrame(
            [
                {
                    "backend": "encoder",
                    "error": "",
                    "load_ms": 100.0,
                    "cold_call_ms": 50.0,
                    "warm_p50_ms": 20.0,
                    "warm_p95_ms": 30.0,
                    "model_size_mb": 500.0,
                    "peak_total_mb": 900.0,
                },
                {
                    "backend": "llama",
                    "error": "backend unavailable",
                    "load_ms": np.nan,
                    "cold_call_ms": np.nan,
                    "warm_p50_ms": np.nan,
                    "warm_p95_ms": np.nan,
                    "model_size_mb": np.nan,
                    "peak_total_mb": np.nan,
                },
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operational.png"
            plot_operational_performance(summary, path)
            self.assertGreater(path.stat().st_size, 0)


class ModelSelectionTests(unittest.TestCase):
    def test_selected_model_names_map_to_runtime_backends(self):
        self.assertEqual(
            selected_models(SimpleNamespace(model=["encoder", "ml", "llm"], backend=None)),
            ["encoder", "ml", "llm"],
        )
        self.assertEqual(
            selected_models(SimpleNamespace(model=["all"], backend=None)),
            ["llama", "encoder", "ml", "claude"],
        )
        self.assertEqual(
            selected_models(SimpleNamespace(model=["claude"], backend=None)),
            ["claude"],
        )
        self.assertEqual(
            selected_models(SimpleNamespace(model=None, backend="encoder-ml")),
            ["encoder", "ml"],
        )
        self.assertEqual(
            selected_models(SimpleNamespace(model=None, backend="llama")),
            ["llm"],
        )
        self.assertEqual(
            selected_models(SimpleNamespace(model=None, backend=None)),
            ["llm", "encoder"],
        )

    def test_rejects_conflicting_or_repeated_model_selection(self):
        with self.assertRaisesRegex(SystemExit, "either --model or"):
            selected_models(SimpleNamespace(model=["ml"], backend="encoder"))
        with self.assertRaisesRegex(SystemExit, "must not be repeated"):
            selected_models(SimpleNamespace(model=["ml", "ml"], backend=None))


def _raw(content: str):
    return SimpleNamespace(content=content)


def _record(review_id, phase, run, category, action, mode="full") -> CallRecord:
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
    def test_valid_json_and_labels(self):
        result = {
            "raw": _raw('{"content_category": "medical", "reply_nature": "reminder"}'),
            "parsed": object(),
            "parsing_error": None,
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertTrue(valid)
        self.assertIsNone(reason)

    def test_invalid_label(self):
        result = {
            "raw": _raw('{"content_category": "Medical?", "reply_nature": "reminder"}'),
            "parsed": object(),
            "parsing_error": None,
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertIn("invalid_category", reason or "")

    def test_non_json(self):
        result = {"raw": _raw("not json"), "parsed": object(), "parsing_error": None}
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertEqual(reason, "raw_not_json")

    def test_parsing_error(self):
        result = {
            "raw": _raw("{}"),
            "parsed": None,
            "parsing_error": "bad schema",
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertIn("parsing_error", reason or "")


class AgreementTests(unittest.TestCase):
    def test_bootstrap_bounds(self):
        point, lo, hi = bootstrap_proportion([True, True, False], 200, 7)
        self.assertAlmostEqual(point, 2 / 3)
        self.assertLessEqual(lo, point)
        self.assertGreaterEqual(hi, point)

    def test_consistency_and_length(self):
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
    def test_nan_error_cell_is_not_an_error(self):
        summary = pd.DataFrame(
            [
                {
                    "backend": "encoder",
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
        self.assertIn("encoder", report)


class FakePredictor:
    def __init__(self, label: str):
        self.label = label
        self.calls = []

    def predict(self, subject: str, body: str, from_addr: str = ""):
        self.calls.append((subject, body, from_addr))
        return self.label, 0.9


def _classifier() -> EncoderClassifier:
    clf = object.__new__(EncoderClassifier)
    clf.tasks = ("category", "action")
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
    def test_body_is_preferred(self):
        self.assertEqual(_model_text(_email("full body", "short preview")), "full body")

    def test_preview_is_used_when_body_is_empty(self):
        self.assertEqual(_model_text(_email("", "short preview")), "short preview")

    def test_whitespace_body_falls_back_to_preview(self):
        self.assertEqual(_model_text(_email("   \n", "short preview")), "short preview")

    def test_both_empty(self):
        self.assertEqual(_model_text(_email("", "")), "")


class AvailabilityTests(unittest.TestCase):
    def test_both_heads_are_required(self):
        clf = _classifier()
        self.assertTrue(clf.available)
        clf._action_clf = None
        self.assertFalse(clf.available)

    def test_load_error_blocks_classification(self):
        clf = _classifier()
        clf._load_error = "missing action head"
        with self.assertRaises(RuntimeError):
            clf.classify(_email("full body", "short preview"))


class ClassifyInputTests(unittest.TestCase):
    def test_both_heads_receive_the_body(self):
        clf = _classifier()
        result = clf.classify(_email("full body", "short preview"))

        self.assertEqual(result.content_category, "medical")
        self.assertEqual(result.reply_nature, "reminder")
        expected = [("Clinic appointment", "full body", "clinic@example.com")]
        self.assertEqual(clf._category_clf.calls, expected)
        self.assertEqual(clf._action_clf.calls, expected)

    def test_both_heads_receive_preview_when_body_is_empty(self):
        clf = _classifier()
        clf.classify(_email("", "short preview"))

        expected = [("Clinic appointment", "short preview", "clinic@example.com")]
        self.assertEqual(clf._category_clf.calls, expected)
        self.assertEqual(clf._action_clf.calls, expected)


if __name__ == "__main__":
    unittest.main()
