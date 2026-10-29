import unittest
from unittest.mock import patch

from app.deadline_extractor import extract_deadline
from app.models import Email
from app.server import create_app


class DeadlineExtractorTests(unittest.TestCase):
    def test_extracts_canvas_due_line_with_singapore_timezone(self):
        candidate = extract_deadline(
            Email(
                id="canvas-assignment",
                subject="Submit Term Paper Deliverables",
                received="2026-10-26T15:53:29+08:00",
                body="A new assignment has been created.\n\ndue: 13 Nov at 23:59",
            )
        )

        self.assertEqual(candidate["date"], "2026-11-13")
        self.assertEqual(candidate["due_at"], "2026-11-13T23:59:00+08:00")
        self.assertFalse(candidate["all_day"])
        self.assertTrue(candidate["year_inferred"])
        self.assertEqual(candidate["text"], "due: 13 Nov at 23:59")
        self.assertEqual(candidate["event_type"], "deadline")

    def test_skips_a_subject_word_that_looks_like_a_month(self):
        candidate = extract_deadline(
            Email(
                id="exam-subject-before-due",
                subject="Bob exam",
                received="2026-10-28T10:15:00+08:00",
                body="due 13 Nov at 23:59",
            )
        )

        self.assertEqual(candidate["date"], "2026-11-13")
        self.assertEqual(candidate["due_at"], "2026-11-13T23:59:00+08:00")
        self.assertEqual(candidate["text"], "due 13 Nov at 23:59")

    def test_reads_a_deadline_that_is_phrased_with_filler_words(self):
        candidate = extract_deadline(
            Email(
                id="deadline-extended",
                subject="Submission deadline extended",
                received="2026-10-28T11:12:00+08:00",
                body="The deadline is now 13 Nov 23:59.",
            )
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["date"], "2026-11-13")
        self.assertEqual(candidate["due_at"], "2026-11-13T23:59:00+08:00")

    def test_extracts_exam_date_without_a_deadline_word(self):
        candidate = extract_deadline(
            Email(
                id="exam-notice",
                subject="Final examination schedule",
                received="2026-10-26T15:53:29+08:00",
                body="Your final exam will be held on 20 Nov 2026 at 9:00 am.",
            )
        )

        self.assertEqual(candidate["date"], "2026-11-20")
        self.assertEqual(candidate["due_at"], "2026-11-20T09:00:00+08:00")
        self.assertEqual(candidate["event_type"], "exam")
        self.assertFalse(candidate["year_inferred"])

    def test_infers_next_year_when_deadline_date_has_passed(self):
        candidate = extract_deadline(
            Email(
                id="year-inference",
                received="2026-12-01T10:00:00+08:00",
                body="Deadline: 13 Nov",
            )
        )

        self.assertEqual(candidate["date"], "2027-11-13")
        self.assertTrue(candidate["year_inferred"])
        self.assertTrue(candidate["all_day"])

    def test_explicit_year_does_not_require_received_date(self):
        candidate = extract_deadline(
            Email(id="explicit-year", body="Submission deadline: Nov 13, 2026")
        )

        self.assertEqual(candidate["date"], "2026-11-13")
        self.assertFalse(candidate["year_inferred"])

    def test_ignores_dates_without_an_explicit_deadline_cue(self):
        candidate = extract_deadline(
            Email(id="unrelated-date", received="2026-10-26T15:00:00+08:00",
                  body="The lecture is on 13 Nov at 23:59.")
        )

        self.assertIsNone(candidate)

    def test_ignores_invalid_deadline_times_instead_of_making_all_day_events(self):
        candidate = extract_deadline(
            Email(
                id="invalid-time",
                received="2026-10-26T15:00:00+08:00",
                body="due: 13 Nov at 25:99",
            )
        )

        self.assertIsNone(candidate)

    @patch("app.server.prepare_text", side_effect=lambda email, _provider: email)
    @patch("app.server.build_provider")
    def test_email_fetch_route_returns_deadline_candidate(
        self, build_provider, _prepare_text
    ):
        class Provider:
            def fetch_emails(self, _limit):
                return [
                    Email(
                        id="canvas-assignment",
                        subject="Term paper",
                        received="2026-10-26T15:53:29+08:00",
                        body="due: 13 Nov at 23:59",
                    )
                ]

        build_provider.return_value = Provider()
        client = create_app(backend="llama").test_client()

        response = client.post(
            "/api/emails",
            json={"provider": "outlook", "credentials": {"token": "test"}, "count": 1},
        )

        self.assertEqual(response.status_code, 200)
        candidate = response.get_json()["emails"][0]["deadline_candidate"]
        self.assertEqual(candidate["date"], "2026-11-13")
        self.assertEqual(candidate["text"], "due: 13 Nov at 23:59")


if __name__ == "__main__":
    unittest.main()
