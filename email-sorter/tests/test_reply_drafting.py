import os
import unittest
from unittest.mock import patch

from app.mail.reply_drafting import ReplyDraftError
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

    @patch("app.routes.replies.generate_reply")
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

    @patch("app.routes.replies.generate_reply")
    def test_reports_configuration_errors(self, generate):
        generate.side_effect = ReplyDraftError("Reply drafting is not configured.", 503)

        response = self.client.post("/api/draft-reply", json={"email": EMAIL})

        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.get_json()["error"])

    def test_rejects_missing_email(self):
        response = self.client.post("/api/draft-reply", json={})

        self.assertEqual(response.status_code, 400)


class SharedKeyTests(unittest.TestCase):
    def _run(self, claude_env_text, existing=None):
        import tempfile
        from pathlib import Path

        from app.mail import reply_drafting

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            if claude_env_text is not None:
                path.write_text(claude_env_text, encoding="utf-8")
            env = {} if existing is None else {"ANTHROPIC_API_KEY": existing}
            with patch.dict("os.environ", env, clear=False), patch.object(
                reply_drafting, "CLAUDE_ENV_PATH", path
            ):
                if existing is None:
                    os.environ.pop("ANTHROPIC_API_KEY", None)
                reply_drafting._use_shared_anthropic_key()
                return os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("CLAUDE_MODEL")

    def test_key_is_taken_from_the_shared_file_only(self):
        key, other = self._run("ANTHROPIC_API_KEY=shared-key\nCLAUDE_MODEL=something\n")
        self.assertEqual(key, "shared-key")
        self.assertIsNone(other)  # nothing else from that file leaks in

    def test_an_existing_key_wins(self):
        key, _ = self._run("ANTHROPIC_API_KEY=shared-key\n", existing="own-key")
        self.assertEqual(key, "own-key")

    def test_missing_file_or_key_is_not_an_error(self):
        self.assertIsNone(self._run(None)[0])
        self.assertIsNone(self._run("OTHER=1\n")[0])


if __name__ == "__main__":
    unittest.main()
