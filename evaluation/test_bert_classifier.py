"""Tests for the BERT backend input selection.

These do not load torch, transformers, or the trained heads. Run from the repo
root:

    .venv/bin/python -m unittest evaluation.test_bert_classifier
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EMAIL_DIR = REPO_ROOT / "email-sorter"
if str(EMAIL_DIR) not in sys.path:
    sys.path.insert(0, str(EMAIL_DIR))

from app.bert_classifier import BertClassifier, _model_text  # noqa: E402
from app.models import Email  # noqa: E402


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
