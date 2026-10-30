"""Tests for the Claude backend; no Anthropic API call is made."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.backends import BACKEND_INFO, list_backends
from app.claude_classifier import ClaudeClassifier
from app.schemas import Email
from app.server import create_app


def _classifier(pipeline_result, last_error=None):
    classifier = ClaudeClassifier.__new__(ClaudeClassifier)
    classifier.my_address = ""
    classifier.cfg = {"preprocess": {"max_chars": 4000}}
    classifier.clf = SimpleNamespace(last_error=last_error)
    classifier.modules = SimpleNamespace(
        preprocess=SimpleNamespace(
            to_record=lambda message, address, cfg: SimpleNamespace(text="record text")
        ),
        pipeline=SimpleNamespace(classify=lambda record, cfg, clf: pipeline_result),
    )
    return classifier


class ClaudeBackendTests(unittest.TestCase):
    def test_backend_is_registered(self):
        self.assertIn("claude", list_backends())
        self.assertEqual(BACKEND_INFO["claude"]["label"], "Claude")

    def test_labels_map_onto_the_email_sorter_taxonomy(self):
        classifier = ClaudeClassifier.__new__(ClaudeClassifier)
        self.assertEqual(classifier.map_topic("FoS General"), "general")
        self.assertEqual(classifier.map_topic("Promotions"), "promotional")
        self.assertEqual(classifier.map_action("Needs a reply"), "needs_reply")
        self.assertEqual(classifier.map_action("Needs an action"), "needs_action")
        self.assertEqual(classifier.map_action("No action needed"), "no_immediate_action")
        self.assertEqual(classifier.map_action("Further review"), "no_immediate_action")

    def test_classify_translates_pipeline_result(self):
        classifier = _classifier(
            SimpleNamespace(
                topic="Promotions",
                action="Needs an action",
                confidence=0.9,
                source="claude",
                reason="asks the reader to register",
                rules_fired=[],
            )
        )

        result = classifier.classify(
            Email(id="1", subject="Workshop", sender="events@nus.edu", body="Register now")
        )

        self.assertEqual(result.content_category, "promotional")
        self.assertEqual(result.reply_nature, "needs_action")
        self.assertIn("asks the reader to register", result.reason)
        self.assertIn("source: claude", result.reason)

    def test_fallback_reports_the_api_error(self):
        classifier = _classifier(
            SimpleNamespace(
                topic="Others",
                action="Further review",
                confidence=0.0,
                source="fallback",
                reason="classification failed",
                rules_fired=[],
            ),
            last_error="api_key_missing",
        )

        result = classifier.classify(Email(id="2", body="hello"))

        self.assertEqual(result.content_category, "others")
        self.assertEqual(result.reply_nature, "no_immediate_action")
        self.assertIn("api_key_missing", result.reason)


class ClaudeServerTests(unittest.TestCase):
    def test_api_advertises_claude_and_reports_readiness(self):
        # This branch adds HTTP Basic auth; skip it for this endpoint test.
        with patch("app.server.install_multiuser", lambda app: None):
            client = create_app(backend="claude").test_client()
        with (
            patch("app.server._ollama_status", return_value=(False, False)),
            patch("app.server.claude_ready", return_value=False),
        ):
            backends = client.get("/api/backends").get_json()["backends"]
            health = client.get("/api/health?backend=claude").get_json()

        claude_backend = next(item for item in backends if item["id"] == "claude")
        self.assertFalse(claude_backend["ready"])
        self.assertFalse(health["backend_ready"])
        self.assertFalse(health["claude_ready"])
