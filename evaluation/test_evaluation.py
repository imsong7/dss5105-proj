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

from app.bert_classifier import BertClassifier, _model_text  # noqa: E402
from app.models import Email  # noqa: E402
from evaluation.quality import (  # noqa: E402
    claude_predictions,
    evaluate_frame,
    llm_predictions,
    plot_offline_quality,
    selected_model_families,
)
from evaluation.performance import (  # noqa: E402
    ALL_MODELS,
    _llama_raw_status,
    plot_operational_performance,
    render_report,
    selected_models,
)
from evaluation.inbox_sorter import load_inbox_modules  # noqa: E402


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


class ModelFamilySelectionTests(unittest.TestCase):
    def test_model_families(self):
        self.assertEqual(selected_model_families("both"), ["encoder", "ml"])
        self.assertEqual(
            selected_model_families("all"), ["encoder", "ml", "llm", "claude"]
        )
        self.assertEqual(selected_model_families("llm"), ["llm"])
        self.assertEqual(selected_model_families("claude"), ["claude"])


class ClaudePredictionTests(unittest.TestCase):
    """Claude is evaluated through the inbox-sorter adapter (no API in tests)."""

    @staticmethod
    def _datasets():
        shared = {
            "Subject": "Clinic",
            "From": "clinic@example.com",
            "Preview": "Appointment notice",
            "Received DateTime": "2026-01-01",
        }
        category = pd.DataFrame(
            [{**shared, "review_id": "a", "label_key": "medical"}]
        )
        action = pd.DataFrame(
            [{**shared, "review_id": "a", "label_key": "reminder"}]
        )
        return {"category": category, "action": action}

    def test_one_call_per_unique_email_and_translated_labels(self):
        class Predictor:
            def __init__(self):
                self.emails = []

            def predict(self, email):
                self.emails.append(email)
                return SimpleNamespace(category="medical", action="reminder")

        predictor = Predictor()
        frames = claude_predictions(self._datasets(), predictor)

        self.assertEqual([email.id for email in predictor.emails], ["a"])
        self.assertEqual(frames["category"]["pred_label"].tolist(), ["medical"])
        self.assertEqual(frames["action"]["pred_label"].tolist(), ["reminder"])
        self.assertTrue((frames["action"]["model_family"] == "claude").all())
        self.assertTrue(frames["action"]["source"].eq("claude").all())
        self.assertTrue(frames["action"]["fold"].isna().all())

    def test_limit_only_calls_and_keeps_the_budgeted_emails(self):
        datasets = self._datasets()
        extra = {
            **datasets["category"].iloc[0].to_dict(),
            "review_id": "b",
            "label_key": "career",
        }
        datasets["category"] = pd.concat(
            [datasets["category"], pd.DataFrame([extra])], ignore_index=True
        )
        datasets["action"] = pd.concat(
            [
                datasets["action"],
                pd.DataFrame([{**extra, "label_key": "needs_reply"}]),
            ],
            ignore_index=True,
        )

        class Predictor:
            def __init__(self):
                self.emails = []

            def predict(self, email):
                self.emails.append(email)
                return SimpleNamespace(category="medical", action="reminder")

        predictor = Predictor()
        frames = claude_predictions(datasets, predictor, limit=1)

        self.assertEqual(len(predictor.emails), 1)
        self.assertEqual(len(frames["category"]), 1)
        self.assertEqual(len(frames["action"]), 1)
        self.assertEqual(frames["action"]["review_id"].tolist(), ["a"])


class EvaluateFrameTests(unittest.TestCase):
    def test_summary_row(self):
        frame = pd.DataFrame(
            {
                "true_label": ["a", "a", "b", "b"],
                "pred_label": ["a", "b", "b", "b"],
            }
        )
        summary = evaluate_frame("toy", "task", frame, ["a", "b"])
        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["accuracy"], 0.75)
        self.assertAlmostEqual(summary["macro_f1"], 0.7333333333333334)
        self.assertEqual(summary["dataset"], "toy")
        self.assertNotIn("accuracy_ci_low", summary)


class EvaluationPlotTests(unittest.TestCase):
    def test_offline_quality_plot_draws_accuracy_and_macro_f1(self):
        summary = pd.DataFrame(
            [
                {
                    "dataset": "action",
                    "model_family": family,
                    "accuracy": accuracy,
                    "macro_f1": f1,
                }
                for family, accuracy, f1 in (
                    ("encoder", 0.8, 0.7),
                    ("ml", 0.75, 0.65),
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
                    "backend": "bert",
                    "error": "",
                    "warm_p50_ms": 20.0,
                    "peak_total_mb": 900.0,
                },
                {
                    "backend": "llama",
                    "error": "backend unavailable",
                    "warm_p50_ms": np.nan,
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
            selected_models(SimpleNamespace(model=["bert", "ml", "llm"])),
            ["bert", "ml", "llm"],
        )
        self.assertEqual(
            selected_models(SimpleNamespace(model=None)),
            ["llm", "bert"],
        )

    def test_all_expands_to_the_four_methods(self):
        self.assertEqual(
            selected_models(SimpleNamespace(model=["all"])),
            ALL_MODELS,
        )
        self.assertEqual(ALL_MODELS, ["llama", "bert", "ml", "claude"])

    def test_rejects_repeated_model_selection(self):
        with self.assertRaisesRegex(SystemExit, "must not be repeated"):
            selected_models(SimpleNamespace(model=["ml", "ml"]))
        with self.assertRaisesRegex(SystemExit, "must not be repeated"):
            selected_models(SimpleNamespace(model=["all", "bert"]))


def _raw(content: str):
    return SimpleNamespace(content=content)


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


class ReportTests(unittest.TestCase):
    def test_nan_error_cell_is_not_an_error(self):
        summary = pd.DataFrame(
            [
                {
                    "backend": "bert",
                    "error": float("nan"),
                    "sample_n": 1,
                    "warm_p50_ms": 5.0,
                    "peak_total_mb": 500.0,
                    "input_tokens_mean": 10.0,
                    "output_tokens_mean": 0.0,
                    "invalid_format_rate": None,
                },
                {
                    "backend": "claude",
                    "error": "",
                    "sample_n": 1,
                    "warm_p50_ms": 800.0,
                    "peak_total_mb": 100.0,
                    "input_tokens_mean": 500.0,
                    "output_tokens_mean": 60.0,
                    "invalid_format_rate": 0.0,
                },
            ]
        )
        manifest = {
            "sample_n": 1,
            "total_rows": 1,
            "runs": 5,
            "seed": 42,
            "body_char_limit": 3000,
            "sample_action_counts": {},
        }
        report = render_report(summary, manifest)
        self.assertNotIn("ERROR", report)
        self.assertIn("bert", report)
        self.assertIn("claude", report)
        self.assertIn("Invalid", report)


class InboxSorterAdapterTests(unittest.TestCase):
    """The inbox-sorter adapter must not need an API key to be inspected."""

    def test_labels_map_onto_the_email_sorter_taxonomy(self):
        from evaluation.inbox_sorter import InboxSorterBackend

        backend = InboxSorterBackend.__new__(InboxSorterBackend)
        self.assertEqual(backend.map_topic("FoS General"), "general")
        self.assertEqual(backend.map_topic("Career"), "career")
        self.assertEqual(backend.map_topic("Medical"), "medical")
        self.assertEqual(backend.map_topic("Promotions"), "promotional")
        self.assertEqual(backend.map_topic("Canvas"), "canva")
        self.assertEqual(backend.map_topic("Others"), "others")
        self.assertEqual(backend.map_action("Needs a reply"), "needs_reply")
        self.assertEqual(backend.map_action("Needs an action"), "needs_action")
        self.assertEqual(backend.map_action("Reminder"), "reminder")
        self.assertEqual(backend.map_action("No action needed"), "no_immediate_action")
        # The inbox-sorter fallback action has no email-sorter equivalent.
        self.assertEqual(backend.map_action("Further review"), "no_immediate_action")

    def test_unknown_labels_fall_back_to_the_email_sorter_defaults(self):
        from evaluation.inbox_sorter import InboxSorterBackend

        backend = InboxSorterBackend.__new__(InboxSorterBackend)
        self.assertEqual(backend.map_topic("Brand new topic"), "others")
        self.assertEqual(backend.map_action("Brand new action"), "no_immediate_action")

    def test_loading_the_inbox_sorter_does_not_shadow_other_packages(self):
        from evaluation.inbox_sorter import load_inbox_modules

        modules = load_inbox_modules()
        self.assertTrue(modules.config.__name__.startswith("inbox_sorter."))
        self.assertTrue(modules.llm.__name__.startswith("inbox_sorter."))
        # email-sorter's `app` and text-encoders' `src` must stay importable.
        import app.config
        import src.data

        self.assertIn("email-sorter", app.config.__file__)
        self.assertIn("text-encoders", src.data.__file__)

    def test_prediction_reports_the_pipeline_source_and_tokens(self):
        from evaluation.inbox_sorter import InboxSorterBackend

        backend = InboxSorterBackend.__new__(InboxSorterBackend)
        backend.my_address = ""
        backend.modules = load_inbox_modules()
        backend.cfg = backend.modules.config.get_config()
        backend.clf = SimpleNamespace(
            model="claude-haiku-5-5",
            enabled=True,
            last_raw_text='{"topic": "Career", "action": "Needs a reply"}',
            last_usage={"input_tokens": 120, "output_tokens": 30},
            last_stop_reason="end_turn",
            last_error=None,
            api_failed=False,
        )
        backend.mapping_notes = []

        class FakePipeline:
            @staticmethod
            def classify(record, cfg, claude):
                return SimpleNamespace(
                    topic="Career",
                    action="Needs a reply",
                    confidence=0.9,
                    source="claude",
                    reason="asks a question",
                    rules_fired=[],
                )

        backend.modules = SimpleNamespace(**vars(backend.modules))
        backend.modules.pipeline = FakePipeline

        result = backend.predict(
            Email(
                id="1",
                subject="Internship",
                sender="career@nus.edu",
                body="Are you free for a call?",
            )
        )

        self.assertEqual(result.category, "career")
        self.assertEqual(result.action, "needs_reply")
        self.assertTrue(result.raw_valid)
        self.assertEqual(result.input_tokens, 120)
        self.assertEqual(result.output_tokens, 30)
        self.assertEqual(result.source, "claude")
        self.assertGreater(result.input_chars, 0)


class FakePredictor:
    def __init__(self, label: str):
        self.label = label
        self.calls = []

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
