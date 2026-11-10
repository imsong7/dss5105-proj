import unittest
from datetime import datetime, timezone

from app import calendar_feed
from app.server import create_app


class IcsTests(unittest.TestCase):
    def test_timed_and_all_day_events(self):
        text = calendar_feed.build_ics(
            "Deadlines",
            [
                {"key": "a", "title": "Final, exam; DSS5105", "date": "2026-12-20", "time": "09:00", "detail": "Bring ID\nOn time", "url": "https://canvas.nus.edu.sg/x"},
                {"key": "b", "title": "Quiz", "date": "2026-11-13", "time": "", "detail": "", "url": ""},
            ],
            now=datetime(2026, 11, 6, tzinfo=timezone.utc),
        )
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(text.endswith("END:VCALENDAR\r\n"))
        self.assertIn("SUMMARY:Final\\, exam\\; DSS5105", text)
        self.assertIn("DTSTART:20261220T010000Z", text)  # 09:00 SGT is 01:00 UTC
        self.assertIn("DTSTART;VALUE=DATE:20261113", text)
        self.assertIn("DTEND;VALUE=DATE:20261114", text)
        self.assertIn("DESCRIPTION:Bring ID\\nOn time", text)
        self.assertEqual(text.count("BEGIN:VEVENT"), 2)

    def test_long_lines_are_folded(self):
        text = calendar_feed.build_ics(
            "x", [{"key": "a", "title": "T" * 200, "date": "2026-11-13", "time": "", "detail": "", "url": ""}]
        )
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75)

    def test_bad_items_are_dropped(self):
        store = calendar_feed.FeedStore(__import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "f.json")
        count = store.set_items("a", [
            {"key": "k", "title": "ok", "date": "2026-11-13"},
            {"key": "k2", "title": "", "date": "2026-11-13"},
            {"key": "k3", "title": "t", "date": "nope"},
            "junk",
        ])
        self.assertEqual(count, 1)


class FeedApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(backend="llama", provider="graphtoken").test_client()

    def test_sync_then_fetch_with_token(self):
        info = self.client.get("/api/feed").get_json()
        self.assertIn("/feed/", info["url"])
        self.assertTrue(info["webcal"].startswith("webcal://"))

        self.client.post("/api/feed/sync", json={"items": [{"key": "m1", "title": "Assignment 1", "date": "2026-11-08"}]})
        self.client.post("/api/events", json={"title": "Study group", "date": "2026-11-09", "time": "14:00"})

        path = "/feed/" + info["url"].rsplit("/feed/", 1)[1]
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/calendar")
        body = response.get_data(as_text=True)
        self.assertIn("SUMMARY:Assignment 1", body)
        self.assertIn("SUMMARY:Study group", body)

    def test_wrong_token_is_404_and_rotate_invalidates(self):
        info = self.client.get("/api/feed").get_json()
        path = "/feed/" + info["url"].rsplit("/feed/", 1)[1]
        self.assertEqual(self.client.get("/feed/wrong.ics").status_code, 404)

        self.client.post("/api/feed/rotate")
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get("/feed/.ics").status_code, 404)
