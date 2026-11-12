"""Event cards read from the email text (app/extract/events.py)."""

import unittest
from unittest.mock import patch

from app.extract.events import parse_event
from app.schemas import Email
from app.server import create_app

RECEIVED = "2026-11-01T02:00:00+00:00"

TALK = Email(
    id="talk",
    subject="FW: [NUS Career] AI in Finance Talk",
    received=RECEIVED,
    body=(
        "Dear students,\n\nJoin us for a talk on AI in finance.\n"
        "Register by 10 Nov: https://forms.gle/abc123\n\n"
        "Date: 14 Nov 2026, 2pm - 4pm\n"
        "Venue: LT27, Faculty of Science. Light refreshments provided.\n\n"
        "Follow us https://www.instagram.com/nus\n"
        "Unsubscribe: https://mail.example.com/unsubscribe"
    ),
)


class ParseEventTests(unittest.TestCase):
    def test_reads_title_date_time_venue_and_signup_link(self):
        event = parse_event(TALK)
        self.assertEqual(event["title"], "AI in Finance Talk")  # FW: and [tag] dropped
        self.assertEqual(event["when"]["date"], "2026-11-14")
        self.assertEqual(event["when"]["time"], "2pm - 4pm")
        self.assertEqual(event["venue"], "LT27, Faculty of Science")
        self.assertEqual([link["url"] for link in event["links"]], ["https://forms.gle/abc123"])
        self.assertFalse(event["has_image"])

    def test_skips_a_signup_deadline_for_the_event_date(self):
        email = Email(id="x", subject="Python workshop", received=RECEIVED,
                      body="Registration closes 5 Nov.\nThe workshop is on 12 Nov 2026 at 3pm.\nVenue: LT27")
        self.assertEqual(parse_event(email)["when"]["date"], "2026-11-12")

    def test_coursework_deadline_is_not_an_event(self):
        email = Email(id="x", subject="Assignment 3", received=RECEIVED,
                      body="Please submit assignment 3 by 13 Nov 23:59 on Canvas.")
        self.assertIsNone(parse_event(email))

    def test_event_without_a_date_has_no_card(self):
        self.assertIsNone(parse_event(Email(id="x", subject="Workshop series", body="Coming soon.")))

    def test_a_long_paragraph_is_never_taken_as_the_venue(self):
        email = Email(id="x", subject="Career fair", received=RECEIVED, body=(
            "The annual career fair returns on 20 Nov 2026 at 10am in the MPSH 2 hall with over 80 "
            "employers, so bring your CV and come early to meet recruiters from many firms.\n"
            "Register: https://forms.gle/xyz"))
        event = parse_event(email)
        self.assertEqual(event["when"]["date"], "2026-11-20")
        self.assertEqual(event["venue"], "")


class ConservativeEventTests(unittest.TestCase):
    """A wrong card is worse than none: each of these gets no card."""

    BODY = "Date: 14 Nov 2026, 2pm - 4pm\nVenue: LT27"

    def card(self, subject="AI talk", body=BODY, sender="events@nus.edu.sg"):
        return parse_event(Email(id="x", subject=subject, sender=sender, received=RECEIVED, body=body))

    def test_the_baseline_gets_a_card(self):
        self.assertIsNotNone(self.card())

    def test_event_word_only_in_the_body(self):
        self.assertIsNone(self.card(subject="Update", body="Join the talk.\n" + self.BODY))

    def test_a_reply_thread(self):
        self.assertIsNone(self.card(subject="RE: AI talk"))

    def test_a_canvas_notice(self):
        self.assertIsNone(self.card(body=self.BODY + "\nView announcement"))
        self.assertIsNone(self.card(sender="notifications@instructure.com"))

    def test_a_date_without_a_time(self):
        self.assertIsNone(self.card(body="Date: 14 Nov 2026\nVenue: LT27"))

    def test_no_venue_and_no_signup_link(self):
        self.assertIsNone(self.card(body="Date: 14 Nov 2026, 2pm\nMore at https://nus.edu.sg/news"))

    def test_a_digest_with_many_dates(self):
        body = "\n".join(f"Talk {n}: {n + 10} Nov 2026, 2pm, LT27" for n in range(5))
        self.assertIsNone(self.card(subject="This week's events", body=body))


class EventRouteTests(unittest.TestCase):
    def fetch(self, emails):
        class Provider:
            def fetch_emails(self, _query):
                return emails

        with patch("app.routes.mail.build_provider", return_value=Provider()), patch(
            "app.routes.mail.prepare_text", side_effect=lambda email, _provider, *_owner: email
        ):
            client = create_app(backend="llama").test_client()
            response = client.post(
                "/api/emails", json={"provider": "outlook", "credentials": {"token": "t"}, "count": 5}
            )
        return {item["id"]: item for item in response.get_json()["emails"]}

    def test_emails_carry_an_event_card(self):
        found = self.fetch([TALK, Email(id="plain", subject="Hello", body="Just saying hi.")])
        self.assertEqual(found["talk"]["event"]["venue"], "LT27, Faculty of Science")
        self.assertIsNone(found["plain"]["event"])

    def test_a_poster_card_wins_over_the_text(self):
        poster = TALK.model_copy(update={"id": "poster", "poster": {"title": "From image"}})
        self.assertIsNone(self.fetch([poster])["poster"]["event"])


if __name__ == "__main__":
    unittest.main()
