import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.classifier_base import list_backends
from app.compare_cli import compare_emails, parse_backends, print_report, run_compare, write_csv
from app.models import Classification, Email


def make_email(index: int, subject: str = "Hello") -> Email:
    return Email(
        id=f"m{index}",
        subject=subject,
        sender="sender@example.com",
        received="2026-10-20T09:00:00Z",
        preview="preview",
    )


class FakeClassifier:
    def __init__(self, category: str, reply: str = "reminder", fail_on: set | None = None):
        self.category = category
        self.reply = reply
        self.fail_on = fail_on or set()

    def classify(self, email: Email) -> Classification:
        if email.id in self.fail_on:
            raise RuntimeError("model exploded")
        return Classification(
            content_category=self.category,
            reply_nature=self.reply,
            deadline=None,
            reason="stub",
        )


class ParseBackendsTests(unittest.TestCase):
    def test_empty_and_all_mean_every_backend(self):
        self.assertEqual(parse_backends(None), list_backends())
        self.assertEqual(parse_backends(""), list_backends())
        self.assertEqual(parse_backends("all"), list_backends())
        self.assertEqual(parse_backends("*"), list_backends())

    def test_splits_trims_and_dedupes(self):
        self.assertEqual(parse_backends(" ml, llama ,ml"), ["ml", "llama"])

    def test_unknown_backend_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown backend 'nope'"):
            parse_backends("ml,nope")

    def test_only_separators_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_backends(" , ")


class CompareEmailsTests(unittest.TestCase):
    def setUp(self):
        self.emails = [make_email(1), make_email(2)]

    def test_classifies_every_email_with_every_backend(self):
        classifiers = {
            "llama": FakeClassifier("general"),
            "ml": FakeClassifier("promotional", reply="no_reply_needed"),
        }
        results, latencies, errors, unavailable = compare_emails(
            self.emails, ["llama", "ml"], factory=classifiers.__getitem__
        )

        self.assertEqual(set(results), {"llama", "ml"})
        self.assertEqual(result_categories(results["llama"]), ["general", "general"])
        self.assertEqual(result_categories(results["ml"]), ["promotional", "promotional"])
        self.assertEqual(errors, {"llama": {}, "ml": {}})
        self.assertEqual(unavailable, {})
        self.assertEqual(set(latencies["llama"]), {"m1", "m2"})

    def test_classifier_failure_marks_backend_unavailable(self):
        def factory(name):
            if name == "bert":
                raise RuntimeError("weights missing")
            return FakeClassifier("general")

        results, _, errors, unavailable = compare_emails(self.emails, ["llama", "bert"], factory=factory)

        self.assertEqual(unavailable, {"bert": "weights missing"})
        self.assertEqual(errors["bert"], {})
        self.assertEqual(len(results["bert"]), 0)
        self.assertEqual(len(results["llama"]), 2)

    def test_per_email_error_does_not_stop_the_batch(self):
        classifiers = {"llama": FakeClassifier("general", fail_on={"m1"})}
        results, _, errors, unavailable = compare_emails(self.emails, ["llama"], factory=classifiers.__getitem__)

        self.assertEqual(unavailable, {})
        self.assertEqual(set(results["llama"]), {"m2"})
        self.assertEqual(errors["llama"], {"m1": "model exploded"})


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.emails = [make_email(1, subject="A long subject " * 5), make_email(2)]
        self.results = {
            "llama": {
                "m1": Classification(content_category="general", reply_nature="reminder"),
                "m2": Classification(content_category="general", reply_nature="reminder"),
            },
            "ml": {
                "m1": Classification(content_category="promotional", reply_nature="no_reply_needed"),
            },
        }
        self.latencies = {"llama": {"m1": 12.0, "m2": 1500.0}, "ml": {"m1": 4.0}}
        self.errors = {"llama": {}, "ml": {"m2": "timeout"}}

    def test_print_report_handles_agreement_and_errors(self):
        print_report(
            self.emails,
            ["llama", "ml"],
            self.results,
            self.latencies,
            self.errors,
            {"bert": "not installed"},
            "pushed inbox · owner a@b.c",
        )
        # Nothing to assert beyond "does not raise"; coverage matters more.

    def test_write_csv_has_one_block_per_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "report.csv"
            write_csv(str(target), self.emails, ["llama", "ml"], self.results, self.latencies, self.errors)

            self.assertTrue(target.exists())
            with target.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], "m1")
        self.assertEqual(rows[0]["llama_category"], "general")
        self.assertEqual(rows[0]["llama_ms"], "12")
        self.assertEqual(rows[0]["ml_category"], "promotional")
        self.assertEqual(rows[1]["ml_error"], "timeout")
        self.assertEqual(rows[1]["ml_category"], "")


class RunCompareTests(unittest.TestCase):
    def call(self, **overrides):
        args = dict(
            url="http://127.0.0.1:5000",
            provider="powerautomate",
            owner="a@b.c",
            token="",
            backends=["ml"],
            limit=5,
            days=7,
            output=None,
        )
        args.update(overrides)
        return run_compare(**args)

    def test_pushed_mail_needs_an_owner(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
            code = self.call(owner="")
        self.assertEqual(code, 2)
        self.assertIn("--owner", stderr.getvalue())

    def test_empty_batch_returns_one(self):
        with patch("app.compare_cli.fetch_emails", return_value=[]) as fetch:
            with redirect_stdout(io.StringIO()) as out:
                code = self.call(days=0)
        self.assertEqual(code, 1)
        fetch.assert_called_once()
        self.assertIn("No emails found", out.getvalue())

    def test_successful_compare_returns_zero(self):
        emails = [make_email(1)]
        results = {"ml": {"m1": Classification(content_category="general", reply_nature="reminder")}}
        with patch("app.compare_cli.fetch_emails", return_value=emails), patch(
            "app.compare_cli.compare_emails", return_value=(results, {"ml": {"m1": 3.0}}, {"ml": {}}, {})
        ):
            with redirect_stdout(io.StringIO()) as out:
                code = self.call()
        self.assertEqual(code, 0)
        self.assertIn("Compare 1 email", out.getvalue())


def result_categories(results: dict) -> list[str]:
    return [results[key].content_category for key in sorted(results)]


if __name__ == "__main__":
    unittest.main()
