import unittest
from unittest.mock import patch

from app.reply_drafting import ReplyDraftError
from app.server import create_app

EMAIL = {
    "id": "m1",
    "subject": "Assignment extension request",
    "sender": "Prof Tan <prof.tan@example.edu>",
    "received": "2026-11-01T00:00:00+00:00",
    "preview": "Please let me know if you need an extension.",
    "body": "Please let me know if you need an extension for the assignment due on Friday.",
}


class DraftReplyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(backend="llama", provider="graphtoken").test_client()

    @patch("app.server.generate_reply")
    def test_returns_draft_and_maps_the_email(self, generate):
        generate.return_value = {
            "reply": "I would like to request an extension for the assignment due on Friday.",
            "placeholders": [],
            "guardrail_issues": [],
            "provider": "anthropic",
            "model": "claude-haiku-5-5",
        }

        response = self.client.post("/api/draft-reply", json={"email": EMAIL})

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertEqual(body["guardrail_issues"], [])
        sent_email = generate.call_args.args[0]
        self.assertEqual(sent_email.id, "m1")
        self.assertEqual(sent_email.subject, "Assignment extension request")

    @patch("app.server.generate_reply")
    def test_reports_configuration_errors(self, generate):
        generate.side_effect = ReplyDraftError("Reply drafting is not configured.", 503)

        response = self.client.post("/api/draft-reply", json={"email": EMAIL})

        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.get_json()["error"])

    def test_rejects_missing_email(self):
        response = self.client.post("/api/draft-reply", json={})

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
