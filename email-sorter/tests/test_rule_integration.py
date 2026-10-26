import unittest
from unittest.mock import patch

from app.classifier_base import BaseClassifier
from app.models import Classification, Email
from app.server import create_app


class StubClassifier(BaseClassifier):
    name = "llama"

    def classify(self, email: Email) -> Classification:
        return Classification(
            content_category="general",
            reply_nature="reminder",
            deadline=None,
            reason="Model classification.",
        )


class SenderRuleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("app.server.create_classifier", return_value=StubClassifier())
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = create_app(backend="llama").test_client()

    def test_dashboard_v2_page_loads(self):
        response = self.client.get("/dashboard-v2")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Inbox dashboard", response.data)
        self.assertIn(b'id="mailbox-settings" open', response.data)
        self.assertIn(b'<dialog class="email-detail-dialog"', response.data)
        self.assertIn(b"dashboard_v2.js?v=4", response.data)

    def test_root_selects_dashboard_by_version(self):
        v1 = create_app(backend="llama", version=1).test_client().get("/")
        v2 = create_app(backend="llama", version=2).test_client().get("/")

        self.assertIn(b"Your emails", v1.data)
        self.assertNotIn(b"Inbox dashboard", v1.data)
        self.assertIn(b"Inbox dashboard", v2.data)
        self.assertNotIn(b'href="/dashboard-v2"', v2.data)

    def test_sender_rule_overrides_category_for_selected_backend(self):
        response = self.client.post(
            "/api/classify",
            json={
                "backend": "llama",
                "email": {
                    "id": "1",
                    "sender": "Canvas Notifications <notifications@instructure.com>",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["content_category"], "canva")
        self.assertEqual(result["reply_nature"], "reminder")
        self.assertEqual(
            result["reason"],
            "Sender rule matched and set category to canva.",
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


if __name__ == "__main__":
    unittest.main()
