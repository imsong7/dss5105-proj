import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import joblib

from app.backends import BACKEND_INFO, create_classifier, list_backends
from app.hybrid_classifier import HybridClassifier
from app.ml_classifier import MLClassifier
from app.schemas import Classification, Email
from app.server import create_app


class FixedModel:
    def __init__(self, label):
        self.label = label
        self.inputs = []

    def predict(self, values):
        self.inputs.extend(values)
        return [self.label]


class FakeTaskModel:
    """Stands in for one half of the hybrid so no real model is loaded."""

    def __init__(self, task, value):
        self.task = task
        self.value = value
        self.calls = 0

    @property
    def model_name(self):
        return f"{self.task}: fake"

    def predict_category(self, email):
        self.calls += 1
        return self.value

    def predict_action(self, email):
        self.calls += 1
        return self.value


class HybridClassifierTests(unittest.TestCase):
    def test_uses_ml_for_category_and_encoder_for_action(self):
        classifier = HybridClassifier.__new__(HybridClassifier)
        classifier._category = FakeTaskModel("category", "promotional")
        classifier._action = FakeTaskModel("action", "needs_reply")

        result = classifier.classify(
            Email(id="1", subject="Offer", body="Limited discount today")
        )

        self.assertEqual(result.content_category, "promotional")
        self.assertEqual(result.reply_nature, "needs_reply")
        self.assertEqual(classifier._category.calls, 1)
        self.assertEqual(classifier._action.calls, 1)
        self.assertEqual(classifier.name, "hybrid")
        self.assertEqual(
            classifier.model_name,
            "category: fake + action: fake",
        )

    def test_partial_ml_load_reads_only_the_category_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            joblib.dump(FixedModel("Promotions"), model_dir / "email_category_model.joblib")

            classifier = MLClassifier(model_dir, tasks=("category",))

            self.assertEqual(
                classifier.predict_category(Email(id="2", subject="Sale")),
                "promotional",
            )
            self.assertEqual(classifier.model_name, "category: FixedModel")
            with self.assertRaisesRegex(RuntimeError, "action"):
                classifier.predict_action(Email(id="2"))

    def test_hybrid_constructor_only_loads_the_category_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            joblib.dump(FixedModel("FoS General"), model_dir / "email_category_model.joblib")

            with (
                patch("app.hybrid_classifier.MLClassifier", wraps=MLClassifier) as ml_cls,
                patch("app.hybrid_classifier.EncoderClassifier") as encoder_cls,
            ):
                encoder_cls.return_value = FakeTaskModel("action", "reminder")
                classifier = HybridClassifier(models_dir=model_dir)

            ml_cls.assert_called_once_with(models_dir=model_dir, tasks=("category",))
            encoder_cls.assert_called_once_with(models_dir=None, tasks=("action",))
            result = classifier.classify(Email(id="3"))
            self.assertEqual(result.content_category, "general")
            self.assertEqual(result.reply_nature, "reminder")

    def test_backend_is_registered_and_constructible(self):
        self.assertIn("hybrid", list_backends())
        self.assertIn("hybrid", BACKEND_INFO)
        with (
            patch("app.hybrid_classifier.MLClassifier"),
            patch("app.hybrid_classifier.EncoderClassifier"),
        ):
            self.assertIsInstance(create_classifier("hybrid"), HybridClassifier)

    def test_api_reports_hybrid_readiness_from_both_families(self):
        client = create_app(backend="hybrid").test_client()
        backend = next(
            item
            for item in client.get("/api/backends").get_json()["backends"]
            if item["id"] == "hybrid"
        )
        self.assertEqual(backend["label"], "Hybrid (ML + text encoder)")

        with (
            patch("app.server._ollama_status", return_value=(False, False)),
            patch("app.server._ml_ready", return_value=True) as ml_ready,
            patch("app.server._encoder_ready", return_value=True) as encoder_ready,
        ):
            health = client.get("/api/health?backend=hybrid").get_json()

        self.assertTrue(health["backend_ready"])
        self.assertTrue(health["hybrid_ready"])
        ml_ready.assert_any_call(("category",))
        encoder_ready.assert_any_call(("action",))

    def test_api_reports_hybrid_not_ready_when_a_model_family_is_missing(self):
        client = create_app(backend="hybrid").test_client()
        with (
            patch("app.server._ollama_status", return_value=(False, False)),
            patch("app.server._ml_ready", return_value=True),
            patch("app.server._encoder_ready", return_value=False),
        ):
            health = client.get("/api/health?backend=hybrid").get_json()

        self.assertFalse(health["backend_ready"])
        self.assertFalse(health["hybrid_ready"])


if __name__ == "__main__":
    unittest.main()
