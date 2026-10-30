import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline

from app.backends import create_classifier, list_backends
from app.ml_classifier import BalancedComplementNB, MLClassifier
from app.schemas import Email
from app.server import create_app


class FixedModel:
    def __init__(self, label):
        self.label = label
        self.inputs = []

    def predict(self, values):
        self.inputs.extend(values)
        return [self.label]


class MLClassifierTests(unittest.TestCase):
    def test_maps_saved_pipeline_labels_and_uses_email_text(self):
        category = FixedModel("FoS General")
        action = FixedModel("Further review")
        classifier = MLClassifier.__new__(MLClassifier)
        classifier._category_model = category
        classifier._action_model = action

        result = classifier.classify(
            Email(
                id="1",
                subject="  Subject  ",
                preview="Preview text",
                body="  Full body  ",
            )
        )

        self.assertEqual(result.content_category, "general")
        self.assertEqual(result.reply_nature, "no_immediate_action")
        self.assertEqual(category.inputs, ["Subject\nFull body"])
        self.assertEqual(action.inputs, ["Subject\nFull body"])
        self.assertEqual(
            classifier.model_name,
            "category: FixedModel; action: FixedModel",
        )

    def test_uses_preview_when_body_is_missing(self):
        classifier = MLClassifier.__new__(MLClassifier)
        category = FixedModel("Canvas")
        action = FixedModel("Needs a reply")
        classifier._category_model = category
        classifier._action_model = action

        result = classifier.classify(Email(id="2", preview="Preview"))

        self.assertEqual(result.content_category, "canva")
        self.assertEqual(result.reply_nature, "needs_reply")
        self.assertEqual(category.inputs, ["Preview"])

    def test_unknown_model_label_fails_explicitly(self):
        classifier = MLClassifier.__new__(MLClassifier)
        classifier._category_model = FixedModel("Unexpected")
        classifier._action_model = FixedModel("Reminder")

        with self.assertRaisesRegex(ValueError, "Unsupported ML category"):
            classifier.classify(Email(id="3"))

    def test_loads_production_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            category = FixedModel("FoS General")
            action = FixedModel("Reminder")
            joblib.dump(category, model_dir / "email_category_model.joblib")
            joblib.dump(action, model_dir / "required_action_model.joblib")

            classifier = MLClassifier(model_dir)

            result = classifier.classify(Email(id="4"))
            self.assertEqual(result.content_category, "general")
            self.assertEqual(result.reply_nature, "reminder")
            self.assertEqual(
                classifier.model_name,
                "category: FixedModel; action: FixedModel",
            )

    def test_loads_custom_pipeline_serialized_from_standalone_trainer(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            joblib.dump(FixedModel("FoS General"), model_dir / "email_category_model.joblib")
            action_model = Pipeline(
                [
                    ("tfidf", TfidfVectorizer()),
                    ("classifier", BalancedComplementNB()),
                ]
            )
            action_model.fit(
                ["please reply soon", "please answer", "event reminder", "date reminder"],
                ["Needs a reply", "Needs a reply", "Reminder", "Reminder"],
            )

            main_module = sys.modules["__main__"]
            previous_module = BalancedComplementNB.__module__
            previous_class = vars(main_module).get("BalancedComplementNB")
            BalancedComplementNB.__module__ = "__main__"
            setattr(main_module, "BalancedComplementNB", BalancedComplementNB)
            try:
                joblib.dump(action_model, model_dir / "required_action_model.joblib")
            finally:
                BalancedComplementNB.__module__ = previous_module
                if previous_class is None:
                    delattr(main_module, "BalancedComplementNB")
                else:
                    setattr(main_module, "BalancedComplementNB", previous_class)

            classifier = MLClassifier(model_dir)
            result = classifier.classify(Email(id="trainer-pickle", preview="event reminder"))

        self.assertEqual(result.content_category, "general")
        self.assertIn(result.reply_nature, {"needs_reply", "reminder"})
        self.assertEqual(
            classifier.model_name,
            "category: FixedModel; action: BalancedComplementNB",
        )

    def test_missing_production_artifacts_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError,             "train_email_ml"):
                MLClassifier(directory)

    def test_backend_is_registered_and_constructible(self):
        self.assertIn("ml", list_backends())
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            joblib.dump(FixedModel("FoS General"), model_dir / "email_category_model.joblib")
            joblib.dump(FixedModel("Reminder"), model_dir / "required_action_model.joblib")
            with patch("app.ml_classifier.ML_MODELS_DIR", model_dir):
                self.assertIsInstance(create_classifier("ml"), MLClassifier)

    def test_api_advertises_ml_and_reports_missing_models(self):
        client = create_app(backend="ml").test_client()
        with (
            patch("app.server._ollama_status", return_value=(False, False)),
            patch("app.server._ml_ready", return_value=False),
        ):
            backends = client.get("/api/backends").get_json()["backends"]
            health = client.get("/api/health?backend=ml").get_json()

        ml_backend = next(item for item in backends if item["id"] == "ml")
        self.assertFalse(ml_backend["ready"])
        self.assertFalse(health["backend_ready"])
        self.assertFalse(health["ml_ready"])

    def test_sender_rule_skips_ml_classification(self):
        classifier = MLClassifier.__new__(MLClassifier)
        classifier._category_model = FixedModel("FoS General")
        classifier._action_model = FixedModel("Reminder")

        with patch("app.server.create_classifier", return_value=classifier):
            client = create_app(backend="ml").test_client()
            rule_response = client.post(
                "/api/classify",
                json={
                    "backend": "ml",
                    "email": {
                        "id": "5",
                        "sender": "Canvas Notifications <notifications@instructure.com>",
                    },
                },
            )
            self.assertEqual(rule_response.status_code, 200)
            self.assertEqual(
                rule_response.get_json()["model_name"],
                "Sender rule (model skipped)",
            )
            self.assertEqual(classifier._category_model.inputs, [])
            self.assertEqual(classifier._action_model.inputs, [])
            response = client.post(
                "/api/classify",
                json={
                    "backend": "ml",
                    "email": {"id": "6", "sender": "student@example.com"},
                },
            )

        result = rule_response.get_json()
        self.assertEqual(result["content_category"], "canva")
        self.assertEqual(result["reply_nature"], "no_immediate_action")

        response = client.post(
            "/api/classify",
            json={
                "backend": "ml",
                "email": {"id": "6", "sender": "student@example.com"},
            },
        )
        response = client.post(
            "/api/classify",
            json={
                "backend": "ml",
                "email": {"id": "6", "sender": "student@example.com"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["model_name"], "category: FixedModel; action: FixedModel")


if __name__ == "__main__":
    unittest.main()
