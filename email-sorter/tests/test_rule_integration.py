import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.classifiers.backends import BaseClassifier
from app.schemas import Classification, Email
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
            "app.routes.mail.create_classifier", return_value=self.stub_classifier
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = create_app(backend="llama", provider="graphtoken").test_client()

    def test_compare_page_is_gone(self):
        self.assertEqual(self.client.get("/compare").status_code, 404)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            create_app(backend="llama", provider="imap")

    def test_missing_build_explains_how_to_build(self):
        with patch("app.server.REACT_INDEX", Path("/nonexistent/index.html")):
            response = create_app(backend="llama").test_client().get("/")

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"npm run build", response.data)

    def test_react_build_is_served_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_text('<div id="root"></div>', encoding="utf-8")
            with patch("app.server.REACT_INDEX", index):
                client = create_app(backend="llama", provider="graphtoken").test_client()
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'id="root"', response.data)

    def test_session_endpoint_reports_provider(self):
        data = self.client.get("/api/session").get_json()
        self.assertEqual(data["provider"], "outlook")
        self.assertEqual(data["email"], "")
        self.assertGreater(data["maxEmails"], 0)

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
