import unittest
from unittest.mock import patch

from app.calendar import extract_deadline, extract_deadlines
from app.schemas import Email
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

    @patch("app.server.prepare_text", side_effect=lambda email, _provider, *_owner: email)
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


class DeadlinePhrasingTests(unittest.TestCase):
    RECEIVED = "2026-11-06T08:00:00+08:00"

    def read(self, subject, body=""):
        return extract_deadlines(
            Email(id="x", subject=subject, body=body, received=self.RECEIVED)
        )

    def test_reads_many_ways_to_write_a_date(self):
        cases = {
            "Quiz 2 closes on 15/11/2026 11:59pm": ("2026-11-15", "2026-11-15T23:59:00+08:00"),
            "Report due 2026-11-15": ("2026-11-15", None),
            "Deadline: 8th November 2026": ("2026-11-08", None),
            "Assignment due Nov 8th, 2026": ("2026-11-08", None),
            "Submit before 8 November": ("2026-11-08", None),
            "Closing date: 30 Nov 2026": ("2026-11-30", None),
            "Register by 12 Nov": ("2026-11-12", None),
            "Please reply by Nov 12": ("2026-11-12", None),
            "RSVP before 9th of December": ("2026-12-09", None),
            "Deadline 15-11-2026 23:59": ("2026-11-15", "2026-11-15T23:59:00+08:00"),
            "Form due 15.11.26": ("2026-11-15", None),
        }
        for subject, (day, due_at) in cases.items():
            with self.subTest(subject):
                found = self.read(subject)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["date"], day)
                self.assertEqual(found[0].get("due_at"), due_at)

    def test_a_range_ends_on_its_last_day(self):
        self.assertEqual(self.read("Assignment due 8 - 15 Nov")[0]["date"], "2026-11-15")

    def test_by_alone_is_not_a_deadline(self):
        self.assertEqual(self.read("Posted by 5 Nov 2026 admin"), [])

    def test_impossible_dates_are_ignored(self):
        self.assertEqual(self.read("Project due 31 Feb 2026"), [])

    def test_lists_every_date_once_in_reading_order(self):
        found = self.read(
            "Quiz 1 due 10 Nov",
            "Quiz 1 due 10 Nov 2026.\nQuiz 2 due 17 Nov.\nFinal exam 24 Nov 2026 9am",
        )

        self.assertEqual(
            [(item["date"], item["event_type"]) for item in found],
            [("2026-11-10", "deadline"), ("2026-11-17", "deadline"), ("2026-11-24", "exam")],
        )

    def test_extract_deadline_is_the_first_of_them(self):
        email = Email(
            id="x", subject="Due 10 Nov", body="Final exam 24 Nov", received=self.RECEIVED
        )

        self.assertEqual(extract_deadline(email), extract_deadlines(email)[0])


class RelativeDateTests(unittest.TestCase):
    # 6 Nov 2026 is a Friday.
    RECEIVED = "2026-11-06T08:00:00+08:00"

    def read(self, subject, body=""):
        return extract_deadlines(
            Email(id="x", subject=subject, body=body, received=self.RECEIVED)
        )

    def test_today_and_tomorrow(self):
        self.assertEqual(self.read("Report due today")[0]["date"], "2026-11-06")
        found = self.read("Please submit by tomorrow 5pm")[0]
        self.assertEqual(found["date"], "2026-11-07")
        self.assertEqual(found["due_at"], "2026-11-07T17:00:00+08:00")

    def test_weekday_names_count_from_the_day_it_was_sent(self):
        self.assertEqual(self.read("Project due this Friday 11:59pm")[0]["date"], "2026-11-06")
        self.assertEqual(self.read("Reading due Monday")[0]["date"], "2026-11-09")
        self.assertEqual(self.read("Quiz next Monday 2pm")[0]["date"], "2026-11-09")
        self.assertEqual(self.read("Quiz next Friday")[0]["date"], "2026-11-13")

    def test_relative_dates_ask_for_a_check(self):
        self.assertTrue(self.read("Report due tomorrow")[0]["year_inferred"])

    def test_a_weekday_with_a_written_date_uses_the_date(self):
        found = self.read("Assignment due Sunday, 15 November")

        self.assertEqual([item["date"] for item in found], ["2026-11-15"])

    def test_a_written_date_wins_over_a_weekday_word(self):
        found = extract_deadlines(
            Email(
                id="x",
                subject="CA4 submission due Friday 11:59pm",
                body="Please submit. Due: 8 Nov 2026 11:59pm.",
                received="2026-11-07T00:28:00+08:00",
            )
        )

        self.assertEqual([item["date"] for item in found], ["2026-11-08"])

    def test_no_cue_means_no_relative_date(self):
        self.assertEqual(self.read("See you tomorrow"), [])


if __name__ == "__main__":
    unittest.main()


class LinkAddressTests(unittest.TestCase):
    def test_a_link_between_cue_and_date_does_not_hide_the_deadline(self):
        from app.calendar import extract_deadlines
        email = Email(
            id="x",
            subject="Form",
            body="Please submit<https://forms.gle/abc> by 16 Nov 2026.",
            received="2026-11-11T03:00:00Z",
        )
        self.assertEqual(extract_deadlines(email)[0]["date"], "2026-11-16")
