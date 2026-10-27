import unittest
from unittest.mock import patch

from app.classifier_base import BaseClassifier
from app.models import Classification, Email
from app.server import create_app


class StubClassifier(BaseClassifier):
    name = "llama"

    def __init__(self, category="general"):
        self.category = category
        self.calls = 0

    def classify(self, email: Email) -> Classification:
        self.calls += 1
        return Classification(
            content_category=self.category,
            reply_nature="reminder",
            deadline=None,
            reason="Model classification.",
        )


class SenderRuleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stub_classifier = StubClassifier()
        self.patcher = patch(
            "app.server.create_classifier", return_value=self.stub_classifier
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = create_app(backend="llama").test_client()

    def test_dashboard_v2_page_loads(self):
        response = self.client.get("/dashboard-v2")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Inbox dashboard", response.data)
        self.assertIn(b'id="mailbox-settings" open', response.data)
        self.assertIn(b'<dialog class="email-detail-dialog"', response.data)
        self.assertIn(b"dashboard_v2.js?v=7", response.data)

    def test_root_selects_dashboard_by_version(self):
        v1 = create_app(backend="llama", version=1).test_client().get("/")
        v2 = create_app(backend="llama", version=2).test_client().get("/")

        self.assertIn(b"Your emails", v1.data)
        self.assertNotIn(b"Inbox dashboard", v1.data)
        self.assertIn(b"Inbox dashboard", v2.data)
        self.assertNotIn(b'href="/dashboard-v2"', v2.data)

    def test_sender_rule_overrides_category_for_selected_backend(self):
        self.stub_classifier.category = "others"
        response = self.client.post(
            "/api/classify",
            json={
                "backend": "llama",
                "email": {
                    "id": "1",
                    "sender": (
                        "CloseDSS5202 Sustainable Systems Analysis [2610] "
                        "<notifications@instructure.com>"
                    ),
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["content_category"], "canva")
        self.assertEqual(result["reply_nature"], "no_immediate_action")
        self.assertEqual(
            result["reason"],
            "Sender rule matched and set category to canva.",
        )
        self.assertEqual(self.stub_classifier.calls, 0)

    def test_taxonomy_displays_rule_category_as_canva(self):
        response = self.client.get("/api/taxonomy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["content"]["canva"]["label"],
            "Canva",
        )

    def test_unmatched_sender_keeps_backend_category(self):
        response = self.client.post(
            "/api/classify",
            json={
                "backend": "llama",
                "email": {"id": "2", "sender": "student@example.com"},
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["content_category"], "general")
        self.assertEqual(result["reason"], "Model classification.")
        self.assertEqual(result["model_name"], "llama")
        self.assertEqual(self.stub_classifier.calls, 1)


if __name__ == "__main__":
    unittest.main()
