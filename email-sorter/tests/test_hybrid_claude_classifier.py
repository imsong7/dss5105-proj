"""Tests for the ML-category + Claude-action hybrid; no API call is made."""

import unittest
from types import SimpleNamespace

from app.backends import BACKEND_INFO, list_backends
from app.hybrid_classifier import HybridClaudeClassifier
from app.schemas import Email


class HybridClaudeTests(unittest.TestCase):
    def test_backend_is_registered(self):
        self.assertIn("hybrid_claude", list_backends())
        self.assertEqual(
            BACKEND_INFO["hybrid_claude"]["label"], "Hybrid (ML + Claude)"
        )

    def test_combines_ml_category_with_claude_action(self):
        classifier = HybridClaudeClassifier.__new__(HybridClaudeClassifier)
        classifier._category = SimpleNamespace(predict_category=lambda email: "career")
        classifier._action = SimpleNamespace(
            classify=lambda email: SimpleNamespace(
                reply_nature="needs_reply",
                deadline=None,
                reason="asks a question",
            )
        )

        result = classifier.classify(Email(id="1", subject="Internship"))

        self.assertEqual(result.content_category, "career")
        self.assertEqual(result.reply_nature, "needs_reply")
        self.assertIn("asks a question", result.reason)
