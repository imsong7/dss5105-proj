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
REPO = HERE.parents[1]  # repo root (llm-reply lives in email-sorter/)
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

    def test_prompt_handles_unknown_rsvp_naturally(self) -> None:
        system, _ = g.build_prompt(make_email(), "Amelia Kang")
        self.assertIn("I will confirm my attendance by [date]", system)
        self.assertIn("at an event (not a consultation session)", system)
        self.assertIn("Use the RSVP deadline if the sender gave one", system)
        self.assertIn("Do not insert a placeholder into a sentence that claims to confirm attendance", system)

    def test_prompt_confirms_an_offered_time_directly(self) -> None:
        system, _ = g.build_prompt(make_email(), "Amelia Kang")
        self.assertIn("Yes, [offered time] works for me.", system)
        self.assertIn("Never respond to a proposed time by asking the sender", system)
        self.assertIn("do not add an availability placeholder when a concrete time was offered", system)
        self.assertIn("If the sender invites you to a consultation or meeting but gives no specific time", system)

    def test_prompt_treats_extension_as_request(self) -> None:
        system, _ = g.build_prompt(make_email(), "Amelia Kang")
        self.assertIn("rather than granting it, request it explicitly", system)
        self.assertIn("Do not say it has already been granted", system)
        self.assertIn("I would like to request an extension", system)
        self.assertIn("until when", system)
        self.assertIn("Do not propose a new date", system)
        self.assertIn("Do not write \"I appreciate the extension\"", system)

    def test_prompt_forbids_invented_dates_and_times(self) -> None:
        system, _ = g.build_prompt(make_email(), "Amelia Kang")
        self.assertIn("Never invent a specific time, date, location, or deadline", system)
        self.assertIn("answer using those options", system)

    def test_prompt_limits_most_replies(self) -> None:
        system, _ = g.build_prompt(make_email(), "Amelia Kang")
        self.assertIn("Keep most replies to 3 sentences or fewer", system)

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


class GuardrailTests(unittest.TestCase):
    def test_clean_reply_has_no_issues(self) -> None:
        self.assertEqual(g.guardrail_issues("Thanks, noted.", make_email()), [])

    def test_raw_sender_address_is_flagged(self) -> None:
        issues = g.guardrail_issues("Please contact prof@nus.edu.sg.", make_email())
        self.assertTrue(any("raw email address" in issue for issue in issues))

    def test_ai_phrase_is_flagged(self) -> None:
        issues = g.guardrail_issues("As an AI, I cannot attend.", make_email())
        self.assertTrue(any("AI/assistant" in issue for issue in issues))

    def test_extension_offer_accepts_request_wording(self) -> None:
        email = make_email(body="Please let me know if you need an extension for the assignment due on Friday.")
        reply = (
            "Dear Prof Tan,\n\n"
            "I would like to request an extension for the assignment due on Friday.\n\n"
            "Best,\nAmelia"
        )
        self.assertEqual(g.guardrail_issues(reply, email), [])

    def test_extension_offer_accepts_appreciate_request(self) -> None:
        email = make_email(body="Please let me know if you need an extension for the assignment due on Friday.")
        reply = "I would appreciate an extension for the assignment due on Friday."
        self.assertEqual(g.guardrail_issues(reply, email), [])

    def test_extension_offer_flags_granted_wording(self) -> None:
        email = make_email(body="Please let me know if you need an extension for the assignment due on Friday.")
        issues = g.guardrail_issues("I appreciate the extension. I will submit by the extended deadline.", email)
        self.assertTrue(any("offered extension as already granted" in issue for issue in issues))

    def test_unlisted_placeholder_is_flagged(self) -> None:
        issues = g.guardrail_issues("Could we meet on [confirm date]?", make_email())
        self.assertTrue(any("not listed" in issue for issue in issues))

    def test_listed_placeholder_is_accepted(self) -> None:
        reply = "Could we meet on [confirm date]?\n\nPlaceholders:\n[confirm date] - proposed date"
        self.assertEqual(g.guardrail_issues(reply, make_email()), [])

    def test_duplicate_placeholder_in_body_is_flagged(self) -> None:
        reply = "Meet [confirm date] or [confirm date].\n\nPlaceholders:\n[confirm date] - date"
        issues = g.guardrail_issues(reply, make_email())
        self.assertTrue(any("more than once" in issue for issue in issues))


class CacheTests(unittest.TestCase):
    def _config(self) -> g.LLMConfig:
        return g.LLMConfig(
            "anthropic",
            "claude-sonnet-5-5",
            "test",
            "https://api.anthropic.com",
            0.3,
            800,
            30,
        )

    def _write_cache(self, output_dir: Path, email: g.Email, config: g.LLMConfig) -> str:
        system, user = g.build_prompt(email, "Amelia Kang")
        cache_key = g.draft_cache_key(email, system, user, config)
        record = {
            "id": email.id,
            "internet_message_id": email.internet_message_id,
            "subject": email.subject,
            "from": {"name": email.sender_name, "address": email.sender_email},
            "recipient": {"name": "Prof Tan", "address": "prof@nus.edu.sg"},
            "recipient_needs_filling": False,
            "to": email.to,
            "received": email.received,
            "filter_label": "Needs a reply",
            "filter_confidence": 0.9,
            "provider": config.provider,
            "model": config.model,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "cache_key": cache_key,
            "reply": "Cached reply.",
            "placeholders": [],
            "draft_file": "cached.eml",
        }
        (output_dir / "drafts.json").write_text(
            json.dumps({"drafts": [record]}), encoding="utf-8"
        )
        return cache_key

    def test_matching_cache_skips_llm(self) -> None:
        config = self._config()
        email = make_email()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            self._write_cache(output_dir, email, config)
            args = type("Args", (), {"output": str(output_dir), "force": False})()
            stdout = StringIO()
            with patch.object(g, "call_llm", side_effect=AssertionError("must not call API")):
                with redirect_stdout(stdout):
                    g.write_outputs(
                        [(email, "Needs a reply", 0.9)],
                        args,
                        config,
                        "Amelia Kang",
                        "me@nus.edu.sg",
                    )
            summary = json.loads((output_dir / "drafts.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["cached_count"], 1)
            self.assertEqual(summary["generated_count"], 0)
            self.assertIn("Using cached draft", stdout.getvalue())
            self.assertTrue((output_dir / "cached.eml").exists())

    def test_force_regenerates_cached_draft(self) -> None:
        config = self._config()
        email = make_email()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            self._write_cache(output_dir, email, config)
            args = type("Args", (), {"output": str(output_dir), "force": True})()
            with patch.object(g, "call_llm", return_value="Fresh reply."):
                g.write_outputs(
                    [(email, "Needs a reply", 0.9)],
                    args,
                    config,
                    "Amelia Kang",
                    "me@nus.edu.sg",
                )
            summary = json.loads((output_dir / "drafts.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["generated_count"], 1)
            self.assertEqual(summary["drafts"][0]["reply"], "Fresh reply.")

    def test_cache_key_changes_with_prompt(self) -> None:
        config = self._config()
        email = make_email()
        system, user = g.build_prompt(email, "Amelia Kang")
        first = g.draft_cache_key(email, system, user, config)
        second = g.draft_cache_key(email, system, user + " ", config)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
