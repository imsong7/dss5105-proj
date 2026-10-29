import tempfile
import unittest
from pathlib import Path

from app.academic_calendar import load_academic_calendar
from app.server import create_app


class AcademicCalendarLoaderTests(unittest.TestCase):
    def test_loads_the_nus_calendar(self):
        events = load_academic_calendar()

        self.assertGreaterEqual(len(events), 20)
        self.assertEqual(events[0]["event"], "Semester 1 Orientation")
        self.assertEqual(events[0]["start_date"], "2026-08-03")
        self.assertTrue(events[0]["mark"])
        self.assertEqual(
            set(events[0]),
            {"category", "event", "start_date", "end_date", "scope", "mark", "notes"},
        )
        semester = next(event for event in events if event["event"] == "Semester 1")
        self.assertFalse(semester["mark"])

    def test_events_are_sorted_and_ranges_are_valid(self):
        events = load_academic_calendar()

        keys = [(event["start_date"], event["end_date"], event["event"]) for event in events]
        self.assertEqual(keys, sorted(keys))
        for event in events:
            self.assertLessEqual(event["start_date"], event["end_date"])

    def test_missing_file_returns_no_events(self):
        self.assertEqual(load_academic_calendar("/no/such/calendar.csv"), [])

    def test_malformed_rows_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.csv"
            path.write_text(
                "category,event,start_date,end_date,scope,notes\n"
                "Semester,Good Term,2026-08-10,2026-12-05,University,\n"
                "Semester,Bad Date,not-a-date,2026-12-05,University,\n"
                "Semester,Backwards,2026-12-05,2026-08-10,University,\n"
                ",,2026-09-01,2026-09-01,University,\n",
                encoding="utf-8",
            )

            events = load_academic_calendar(path)

        self.assertEqual([event["event"] for event in events], ["Good Term"])


class AcademicCalendarApiTests(unittest.TestCase):
    def test_endpoint_returns_the_calendar(self):
        response = create_app(backend="hybrid", version=2).test_client().get(
            "/api/academic-calendar"
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["available"])
        self.assertEqual(data["label"], "NUS AY2026/27")
        self.assertTrue(data["events"])
        self.assertIn("event", data["events"][0])


if __name__ == "__main__":
    unittest.main()
