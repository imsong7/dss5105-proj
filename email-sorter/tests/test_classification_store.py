import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stores import classification_store as store
from app.classifiers.backends import BaseClassifier
from app.schemas import Classification
from app.server import create_app

EMAIL = {
    "id": "m1", "subject": "Quiz due 20 Nov", "sender": "Prof <p@u.nus.edu>",
    "received": "2026-11-01T00:00:00+00:00", "preview": "p", "body": "Quiz due 20 Nov",
}


class Counting(BaseClassifier):
    name = "llama"

    def __init__(self):
        self.calls = 0

    def classify(self, email):
        self.calls += 1
        return Classification(
            content_category="general", reply_nature="needs_action",
            deadline=None, reason="Model.",
        )


class ClassifyApiTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.stub = Counting()
        for target, value in (
            ("classify_cache", store.ClassifyCache(root / "c.json")),
            ("correction_store", store.CorrectionStore(root / "r.json")),
        ):
            patcher = patch.object(store, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("app.routes.mail.create_classifier", return_value=self.stub)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = create_app(backend="llama", provider="graphtoken").test_client()

    def classify(self):
        return self.client.post("/api/classify", json={"email": EMAIL, "backend": "llama"}).get_json()

    def test_second_call_uses_cache(self):
        first = self.classify()
        second = self.classify()
        self.assertEqual(self.stub.calls, 1)
        self.assertNotIn("cached", first)
        self.assertTrue(second["cached"])
        self.assertEqual(second["reply_nature"], "needs_action")

    def test_correction_wins_and_can_be_undone(self):
        self.classify()
        saved = self.client.post("/api/corrections", json={
            "email": EMAIL, "backend": "llama",
            "original": {"content_category": "general", "reply_nature": "needs_action"},
            "content_category": "career", "reply_nature": "reminder",
        })
        self.assertEqual(saved.status_code, 201)

        fixed = self.classify()
        self.assertTrue(fixed["corrected"])
        self.assertEqual((fixed["content_category"], fixed["reply_nature"]), ("career", "reminder"))
        self.assertEqual(fixed["original"]["reply_nature"], "needs_action")

        self.assertEqual(self.client.delete("/api/corrections/m1").status_code, 200)
        self.assertEqual(self.classify()["reply_nature"], "needs_action")
        self.assertEqual(self.client.delete("/api/corrections/m1").status_code, 404)

    def test_correction_rejects_unknown_labels(self):
        response = self.client.post("/api/corrections", json={
            "email": EMAIL, "content_category": "nope", "reply_nature": "reminder",
        })
        self.assertEqual(response.status_code, 400)

    def test_correction_is_private_to_owner(self):
        corrections = store.CorrectionStore(Path(tempfile.mkdtemp()) / "r.json")
        corrections.save("a@u.nus.edu", {
            "email": EMAIL, "content_category": "career", "reply_nature": "reminder",
        })
        self.assertIsNone(corrections.get("b@u.nus.edu", "m1"))
        self.assertIsNotNone(corrections.get("a@u.nus.edu", "m1"))


class SenderRuleTests(ClassifyApiTests):
    def correct(self, remember):
        return self.client.post("/api/corrections", json={
            "email": EMAIL, "backend": "llama", "remember_sender": remember,
            "original": {"content_category": "general", "reply_nature": "needs_action"},
            "content_category": "career", "reply_nature": "reminder",
        })

    def other_email(self):
        return {**EMAIL, "id": "m2", "subject": "Another note"}

    def test_rule_applies_to_other_mail_from_same_sender(self):
        self.assertEqual(self.correct(True).get_json()["rule"], True)
        result = self.client.post(
            "/api/classify", json={"email": self.other_email(), "backend": "llama"}
        ).get_json()
        self.assertTrue(result["rule"])
        self.assertEqual((result["content_category"], result["reply_nature"]), ("career", "reminder"))
        self.assertEqual(self.stub.calls, 0)

    def test_without_the_tick_only_that_email_changes(self):
        self.correct(False)
        result = self.client.post(
            "/api/classify", json={"email": self.other_email(), "backend": "llama"}
        ).get_json()
        self.assertNotIn("rule", result)
        self.assertEqual(self.stub.calls, 1)

    def test_undo_removes_the_rule_too(self):
        self.correct(True)
        self.client.delete("/api/corrections/m1")
        result = self.client.post(
            "/api/classify", json={"email": self.other_email(), "backend": "llama"}
        ).get_json()
        self.assertNotIn("rule", result)

    def test_remove_rule_directly(self):
        self.correct(True)
        response = self.client.delete("/api/sender-rules?sender=p@u.nus.edu")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.delete("/api/sender-rules?sender=p@u.nus.edu").status_code, 404)
