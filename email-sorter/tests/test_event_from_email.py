import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.extract import event_from_email as module
from app.extract.event_from_email import ExtractionError, extract_event
from app.schemas import Email
from app.server import create_app

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=module.TIMEZONE)
EMAIL = Email(
    id="m1",
    subject="Group meeting",
    sender="Alex <alex@u.nus.edu>",
    received="2026-11-10T02:00:00+00:00",
    body="Friday 2pm at COM1-0210",
)


class FakeClient:
    def __init__(self, fields=None, reply=None):
        self.calls = []
        block = SimpleNamespace(type="tool_use", input=fields or {})
        self.reply = reply if reply is not None else SimpleNamespace(content=[block])
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


FOUND = {
    "found": True,
    "title": "Group meeting",
    "date": "2026-11-13",
    "start_time": "14:00",
    "location": "COM1-0210",
    "summary": "Bring the draft.",
}


class ExtractEventTests(unittest.TestCase):
    def test_clean_fields_and_location_in_notes(self):
        event = extract_event(EMAIL, client=FakeClient(FOUND), now=NOW)
        self.assertEqual(
            event,
            {
                "title": "Group meeting",
                "date": "2026-11-13",
                "time": "14:00",
                "notes": "Location: COM1-0210\nBring the draft.",
            },
        )

    def test_request_forces_the_tool_and_gives_the_dates(self):
        client = FakeClient(FOUND)
        extract_event(EMAIL, client=client, now=NOW)
        call = client.calls[0]
        self.assertEqual(call["tool_choice"], {"type": "tool", "name": "save_event"})
        self.assertIn("Today is Tuesday 2026-11-10", call["messages"][0]["content"])

    def test_no_event_or_bad_date_is_a_readable_error(self):
        for fields in ({"found": False}, {"found": True, "date": "next Friday"}):
            with self.assertRaises(ExtractionError) as caught:
                extract_event(EMAIL, client=FakeClient(fields), now=NOW)
            self.assertEqual(caught.exception.status_code, 422)

    def test_bad_time_is_dropped_not_guessed(self):
        event = extract_event(EMAIL, client=FakeClient({**FOUND, "start_time": "2pm"}), now=NOW)
        self.assertEqual(event["time"], "")

    def test_reply_without_tool_call(self):
        client = FakeClient(reply=SimpleNamespace(content=[SimpleNamespace(type="text")]))
        with self.assertRaises(ExtractionError):
            extract_event(EMAIL, client=client, now=NOW)

    def test_missing_key_is_a_setup_message(self):
        with patch.object(module, "_api_key", return_value=""):
            with self.assertRaises(ExtractionError) as caught:
                extract_event(EMAIL, now=NOW)
        self.assertEqual(caught.exception.status_code, 503)


class ScanApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(backend="llama", provider="graphtoken").test_client()
        self.payload = {"email": EMAIL.model_dump()}

    def scan(self):
        return self.client.post("/api/events/scan", json=self.payload)

    def test_returns_the_event_and_reads_each_email_once(self):
        fields = {"title": "Group meeting", "date": "2026-11-13", "time": "14:00", "notes": ""}
        with patch("app.routes.planner.extract_event", return_value=fields) as extract:
            first, second = self.scan(), self.scan()
        self.assertEqual(first.get_json(), {"event": fields})
        self.assertEqual(second.get_json(), {"event": fields})
        self.assertEqual(extract.call_count, 1)
        # Scanning does not add anything to the calendar.
        self.assertEqual(self.client.get("/api/events").get_json()["events"], [])

    def test_no_event_is_remembered_too(self):
        with patch("app.routes.planner.extract_event", side_effect=ExtractionError("None.", 422)) as extract:
            first, second = self.scan(), self.scan()
        self.assertEqual((first.status_code, first.get_json()), (200, {"event": None}))
        self.assertEqual(second.get_json(), {"event": None})
        self.assertEqual(extract.call_count, 1)

    def test_failures_are_not_remembered(self):
        with patch("app.routes.planner.extract_event", side_effect=ExtractionError("No key.", 503)):
            self.assertEqual(self.scan().status_code, 503)
        fields = {"title": "T", "date": "2026-11-13", "time": "", "notes": ""}
        with patch("app.routes.planner.extract_event", return_value=fields):
            self.assertEqual(self.scan().get_json(), {"event": fields})

    def test_rejects_malformed_requests(self):
        for body in ({}, {"email": {"subject": "no id"}}):
            self.assertEqual(self.client.post("/api/events/scan", json=body).status_code, 400)


if __name__ == "__main__":
    unittest.main()
