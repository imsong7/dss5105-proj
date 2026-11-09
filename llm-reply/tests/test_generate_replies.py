from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(HERE))

import generate_replies as g  # noqa: E402


def make_email(**overrides) -> g.Email:
    data = {
        "id": "id-1",
        "internet_message_id": "<id-1@example.com>",
        "subject": "Quick question",
        "sender_name": "Prof Tan",
        "sender_email": "prof@nus.edu.sg",
        "to": [{"address": "me@nus.edu.sg"}],
        "received": "2026-09-15T05:11:55Z",
        "body": "Could you confirm the date?",
    }
    data.update(overrides)
    return g.Email(**data)


def make_args(**overrides):
    data = {
        "filter": "needs-reply",
        "ids": "",
        "limit": 0,
        "include_actions": False,
        "skip_noreply": True,
        "skip_broadcast": True,
        "skip_domains": "",
        "min_confidence": 0.0,
        "sender_name": "",
        "sender_email": "",
        "no_confirm": True,
    }
    data.update(overrides)
    return type("Args", (), data)()


class ClaudeActionClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        config = g.LLMConfig("anthropic", "claude-sonnet-5-5", "test", "https://api.anthropic.com", 0.3, 800, 30)
        self.classifier = g.ClaudeActionClassifier(config, REPO / "claude" / "config.yaml")

    def test_needs_reply_is_returned(self) -> None:
        answer = '{"topic":"Others","action":"Needs a reply","confidence":0.9}'
        with patch.object(g, "call_llm", return_value=answer):
            action, confidence = self.classifier.classify_email(make_email())
        self.assertEqual(action, g.REPLY_LABEL)
        self.assertAlmostEqual(confidence, 0.9)

    def test_low_confidence_falls_back(self) -> None:
        answer = '{"topic":"Others","action":"Needs a reply","confidence":0.2}'
        with patch.object(g, "call_llm", return_value=answer):
            action, _ = self.classifier.classify_email(make_email())
        self.assertEqual(action, self.classifier.fallback_action)

    def test_noreply_sender_cannot_need_reply(self) -> None:
        answer = '{"topic":"Others","action":"Needs a reply","confidence":0.9}'
        with patch.object(g, "call_llm", return_value=answer):
            action, _ = self.classifier.classify_email(make_email(sender_email="no-reply@example.com"))
        self.assertEqual(action, self.classifier.fallback_action)

    def test_invalid_json_falls_back(self) -> None:
        with patch.object(g, "call_llm", return_value="not json"):
            action, confidence = self.classifier.classify_email(make_email())
        self.assertEqual(action, self.classifier.fallback_action)
        self.assertEqual(confidence, 0.0)

    def test_unknown_label_falls_back(self) -> None:
        answer = '{"topic":"Others","action":"Unknown","confidence":0.9}'
        with patch.object(g, "call_llm", return_value=answer):
            action, _ = self.classifier.classify_email(make_email())
        self.assertEqual(action, self.classifier.fallback_action)


class SelectionTests(unittest.TestCase):
    def test_ids_bypass_filters(self) -> None:
        emails = [
            make_email(id="keep-me", sender_email="notifications@instructure.com"),
            make_email(id="other"),
        ]
        rows = g.select_emails(emails, make_args(ids="keep-me"), classifier=None)
        self.assertEqual([row[0].id for row in rows], ["keep-me"])
        self.assertEqual(rows[0][1], "id")

    def test_instructure_is_not_skipped_by_default(self) -> None:
        emails = [make_email(id="canvas", sender_email="notifications@instructure.com")]
        rows = g.select_emails(emails, make_args(filter="all"), classifier=None)
        self.assertEqual([row[0].id for row in rows], ["canvas"])

    def test_explicit_skip_domain_still_works(self) -> None:
        emails = [
            make_email(id="canvas", sender_email="notifications@instructure.com"),
            make_email(id="ok"),
        ]
        rows = g.select_emails(
            emails,
            make_args(filter="all", skip_domains="instructure.com"),
            classifier=None,
        )
        self.assertEqual([row[0].id for row in rows], ["ok"])

    def test_broadcast_is_skipped_by_default(self) -> None:
        emails = [
            make_email(id="bulk", body="Do not reply to this email."),
            make_email(id="ok"),
        ]
        rows = g.select_emails(emails, make_args(filter="all"), classifier=None)
        self.assertEqual([row[0].id for row in rows], ["ok"])

    def test_keyword_filter_ignores_bare_question(self) -> None:
        email = make_email(subject="News", body="Ready to get involved? Discover what's on.")
        self.assertFalse(g.needs_reply_heuristic(email))

    def test_keyword_filter_keeps_direct_request(self) -> None:
        email = make_email(subject="News", body="Please let us know if you can attend.")
        self.assertTrue(g.needs_reply_heuristic(email))

    def test_canvas_footer_does_not_hide_real_request(self) -> None:
        email = make_email(
            body=(
                "Please let us know if you would like to attend.\n\n"
                "Replies to this email will be posted as a reply to the announcement."
            )
        )
        self.assertFalse(g.is_broadcast(email))

    def test_canvas_footer_without_request_is_still_broadcast(self) -> None:
        email = make_email(
            body=(
                "Registration is open.\n\n"
                "Replies to this email will be posted as a reply to the announcement."
            )
        )
        self.assertTrue(g.is_broadcast(email))


class ClassifierLoadTests(unittest.TestCase):
    def test_default_classifier_is_offline(self) -> None:
        self.assertIn(g.DEFAULT_CLASSIFIER, ("ml", "keywords"))

    @unittest.skipUnless(g.DEFAULT_MODEL.exists(), "local joblib artifact not available")
    def test_local_ml_model_loads(self) -> None:
        self.assertIsNotNone(g.load_classifier(g.DEFAULT_MODEL))


class SenderTests(unittest.TestCase):
    def test_detects_owner_from_to_recipient(self) -> None:
        emails = [
            make_email(to=[{"name": "Amelia Kang", "address": "ameliakang@u.nus.edu"}]),
            make_email(id="id-2", to=[{"name": "Amelia Kang", "address": "ameliakang@u.nus.edu"}]),
        ]
        name, address = g.detect_sender(emails)
        self.assertEqual(address, "ameliakang@u.nus.edu")
        self.assertEqual(name, "Amelia Kang")

    def test_explicit_sender_wins(self) -> None:
        emails = [make_email(to=[{"name": "Amelia Kang", "address": "ameliakang@u.nus.edu"}])]
        args = make_args(sender_name="Jo Tan", sender_email="jo@example.com")
        with patch.dict(g.os.environ, {"REPLY_SENDER_NAME": "", "REPLY_SENDER_EMAIL": ""}):
            name, address = g.resolve_sender(emails, args)
        self.assertEqual((name, address), ("Jo Tan", "jo@example.com"))

    def test_name_falls_back_to_email_local_part(self) -> None:
        emails = [make_email(to=[{"address": "amelia.kang@u.nus.edu"}])]
        args = make_args(sender_name="", sender_email="")
        with patch.dict(g.os.environ, {"REPLY_SENDER_NAME": "", "REPLY_SENDER_EMAIL": ""}):
            name, address = g.resolve_sender(emails, args)
        self.assertEqual(address, "amelia.kang@u.nus.edu")
        self.assertEqual(name, "Amelia Kang")

    def test_missing_owner_is_an_error(self) -> None:
        args = make_args(sender_name="", sender_email="")
        with patch.dict(g.os.environ, {"REPLY_SENDER_NAME": "", "REPLY_SENDER_EMAIL": ""}):
            with self.assertRaises(SystemExit):
                g.resolve_sender([make_email(to=[])], args)

    def test_interactive_prompt_allows_editing(self) -> None:
        emails = [make_email(to=[{"name": "Amelia Kang", "address": "ameliakang@u.nus.edu"}])]
        args = make_args(no_confirm=False)
        with patch.dict(g.os.environ, {"REPLY_SENDER_NAME": "", "REPLY_SENDER_EMAIL": ""}):
            with patch.object(g.sys.stdin, "isatty", return_value=True):
                with patch("builtins.input", side_effect=["new@example.com", "New Name"]):
                    name, address = g.resolve_sender(emails, args)
        self.assertEqual((name, address), ("New Name", "new@example.com"))

    def test_no_confirm_uses_detected_sender(self) -> None:
        emails = [make_email(to=[{"name": "Amelia Kang", "address": "ameliakang@u.nus.edu"}])]
        args = make_args(no_confirm=True)
        with patch.dict(g.os.environ, {"REPLY_SENDER_NAME": "", "REPLY_SENDER_EMAIL": ""}):
            with patch.object(g.sys.stdin, "isatty", return_value=True):
                with patch("builtins.input", side_effect=AssertionError("must not prompt")):
                    name, address = g.resolve_sender(emails, args)
        self.assertEqual((name, address), ("Amelia Kang", "ameliakang@u.nus.edu"))


class DryRunTests(unittest.TestCase):
    def test_dry_run_with_claude_is_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mails.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "canvas-1",
                            "internetMessageId": "<canvas-1@example.com>",
                            "subject": "Consultation",
                            "from": {
                                "emailAddress": {
                                    "name": "Anggi",
                                    "address": "notifications@instructure.com",
                                }
                            },
                            "toRecipients": [
                                {
                                    "emailAddress": {
                                        "name": "Amelia Kang",
                                        "address": "me@nus.edu.sg",
                                    }
                                }
                            ],
                            "receivedDateTime": "2026-09-15T05:11:55Z",
                            "body": {
                                "content": "Please let us know if you would like to attend."
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )
            stdout, stderr = StringIO(), StringIO()
            argv = [
                "generate_replies.py",
                "--input",
                str(path),
                "--dry-run",
                "--classifier",
                "claude",
                "--no-confirm",
            ]
            with patch.object(sys, "argv", argv):
                with patch.object(g, "load_dotenv"):
                    with patch.object(g, "call_llm", side_effect=AssertionError("must not call API")):
                        with patch.object(
                            g,
                            "resolve_config",
                            side_effect=AssertionError("must not resolve API config"),
                        ):
                            with redirect_stdout(stdout), redirect_stderr(stderr):
                                g.main()
            self.assertIn("using keywords instead of Claude", stderr.getvalue())
            self.assertIn("Please let us know", stdout.getvalue())


class OutputTests(unittest.TestCase):
    def test_prompt_requires_explicit_answers(self) -> None:
        system, _ = g.build_prompt(make_email(), "Amelia Kang")
        self.assertIn("RSVP", system)
        self.assertIn("[confirm the group's availability]", system)
        self.assertIn("Never reply with only an acknowledgement", system)

    def test_prompt_offers_to_arrange_discussion(self) -> None:
        system, _ = g.build_prompt(make_email(), "Amelia Kang")
        self.assertIn("optional consultation", system)
        self.assertIn("We would like to arrange a consultation", system)
        self.assertIn("Would [offered slot] work for you?", system)
        self.assertIn("Keep this kind of reply to 2-3 sentences", system)
        self.assertIn("Do not ask whether we want to attend", system)
        self.assertIn("do not promise who else will attend", system)
        self.assertIn("do not add an availability placeholder", system)

    def test_prompt_does_not_copy_raw_addresses(self) -> None:
        system, _ = g.build_prompt(make_email(), "Amelia Kang")
        self.assertIn("Do not copy raw email addresses", system)
        self.assertIn("short acknowledgement", system)

    def test_placeholders_are_sorted_and_unique(self) -> None:
        text = "Meet on [confirm date]. Again [confirm date] and [room]."
        self.assertEqual(g.placeholders_in(text), ["[confirm date]", "[room]"])

    def test_eml_headers_are_safe(self) -> None:
        eml = g.build_eml(
            make_email(sender_name="Prof\nTan"),
            "Thanks.",
            "Amelia",
            "me@nus.edu.sg",
        )
        self.assertIn("To: Prof Tan <prof@nus.edu.sg>", eml)
        self.assertIn("In-Reply-To: <id-1@example.com>", eml)
        self.assertNotIn("Prof\nTan", eml)

    def test_canvas_recipient_is_blank(self) -> None:
        email = make_email(sender_email="notifications@instructure.com")
        self.assertEqual(g.reply_recipient(email), ("", ""))
        eml = g.build_eml(email, "Thanks.", "Amelia", "me@nus.edu.sg")
        self.assertNotIn("To: notifications@instructure.com", eml)
        self.assertNotIn("\nTo:", eml)

    def test_reply_to_overrides_canvas_sender(self) -> None:
        email = make_email(
            sender_email="notifications@instructure.com",
            reply_to=[{"name": "Anggi", "address": "anggi@nus.edu.sg"}],
        )
        self.assertEqual(g.reply_recipient(email), ("Anggi", "anggi@nus.edu.sg"))
        eml = g.build_eml(email, "Thanks.", "Amelia", "me@nus.edu.sg")
        self.assertIn("To: Anggi <anggi@nus.edu.sg>", eml)

    def test_non_canvas_recipient_uses_sender(self) -> None:
        email = make_email(sender_name="Prof Tan", sender_email="prof@nus.edu.sg")
        self.assertEqual(g.reply_recipient(email), ("Prof Tan", "prof@nus.edu.sg"))

    def test_long_message_id_is_not_encoded(self) -> None:
        message_id = (
            "<010801a0a368177b-72ebf342-1b38-4a61-bb2e-d0aff1899575"
            "-000000@ap-southeast-2.amazonses.com>"
        )
        eml = g.build_eml(
            make_email(internet_message_id=message_id),
            "Thanks.",
            "Amelia",
            "me@nus.edu.sg",
        )
        self.assertIn(f"In-Reply-To: {message_id}", eml)
        self.assertNotIn("=?utf-8?q?=3C010801", eml)

    def test_anthropic_payload_has_no_temperature(self) -> None:
        captured = {}

        class Response:
            status_code = 200
            text = ""

            def json(self):
                return {"content": [{"type": "text", "text": "ok"}]}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return Response()

        config = g.LLMConfig("anthropic", "claude-sonnet-5-5", "test", "https://api.anthropic.com", 0.3, 800, 30)
        with patch.object(g.requests, "post", side_effect=fake_post):
            g.call_llm(config, "system", "user")
        self.assertNotIn("temperature", captured["payload"])


if __name__ == "__main__":
    unittest.main()
