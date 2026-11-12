import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import event_extraction, user_events
from app.event_extraction import ExtractionError, extract_event
from app.schemas import Email
from app.server import create_app

SGT = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=SGT)


class FakeClient:
    """Stands in for ``anthropic.Anthropic``; records the request it was given."""

    def __init__(self, tool_input=None, blocks=None, error=None):
        self.calls = []
        self._blocks = blocks if blocks is not None else [
            SimpleNamespace(type="tool_use", input=tool_input or {})
        ]
        self._error = error
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(content=self._blocks)


def make_email(**overrides):
    values = dict(
        id="msg-1",
        subject="Group meeting this Friday",
        sender="Alex <alex@u.nus.edu>",
        received="2026-11-10T02:00:00+00:00",
        body="Let's meet Friday 2pm to 4pm at COM1-0210 to finish the report.",
    )
    values.update(overrides)
    return Email(**values)


GOOD = {
    "found": True,
    "title": "Group meeting",
    "date": "2026-11-13",
    "start_time": "14:00",
    "end_time": "16:00",
    "location": "COM1-0210",
    "summary": "Finish the report together.",
}


class ExtractEventTests(unittest.TestCase):
    def test_returns_clean_event_fields(self):
        client = FakeClient(GOOD)
        event = extract_event(make_email(), client=client, now=NOW)
        self.assertEqual(
            event,
            {
                "title": "Group meeting",
                "date": "2026-11-13",
                "time": "14:00",
                "end_time": "16:00",
                "location": "COM1-0210",
                "notes": "Finish the report together.",
                "email_id": "msg-1",
            },
        )

    def test_request_forces_the_tool_and_gives_claude_the_dates(self):
        client = FakeClient(GOOD)
        extract_event(make_email(), client=client, now=NOW)
        call = client.calls[0]
        self.assertEqual(call["tool_choice"], {"type": "tool", "name": "save_event"})
        content = call["messages"][0]["content"]
        self.assertIn("Today is Thursday 2026-11-12", content)
        self.assertIn("Tuesday 2026-11-10 10:00", content)  # received, in Singapore time
        self.assertIn("COM1-0210", content)
        self.assertIn("untrusted", call["system"])

    def test_long_body_is_cut(self):
        client = FakeClient(GOOD)
        extract_event(make_email(body="x" * 50_000), client=client, now=NOW)
        self.assertLess(len(client.calls[0]["messages"][0]["content"]), 7000)

    def test_no_event_found(self):
        with self.assertRaises(ExtractionError) as caught:
            extract_event(make_email(), client=FakeClient({"found": False}), now=NOW)
        self.assertEqual(caught.exception.status_code, 422)

    def test_bad_date_is_not_stored(self):
        for date in ("", "next Friday", "2026-13-40"):
            with self.assertRaises(ExtractionError) as caught:
                extract_event(make_email(), client=FakeClient({**GOOD, "date": date}), now=NOW)
            self.assertEqual(caught.exception.status_code, 422)

    def test_bad_times_are_dropped_not_guessed(self):
        event = extract_event(
            make_email(), client=FakeClient({**GOOD, "start_time": "2pm", "end_time": "16:00"}), now=NOW
        )
        self.assertEqual((event["time"], event["end_time"]), ("", ""))

        event = extract_event(
            make_email(), client=FakeClient({**GOOD, "start_time": "16:00", "end_time": "14:00"}), now=NOW
        )
        self.assertEqual((event["time"], event["end_time"]), ("16:00", ""))

    def test_title_falls_back_to_subject_and_is_limited(self):
        event = extract_event(
            make_email(subject="Subject line"), client=FakeClient({**GOOD, "title": ""}), now=NOW
        )
        self.assertEqual(event["title"], "Subject line")
        event = extract_event(make_email(), client=FakeClient({**GOOD, "title": "t" * 500}), now=NOW)
        self.assertEqual(len(event["title"]), 100)

    def test_api_failure_becomes_a_readable_error(self):
        with self.assertRaises(ExtractionError) as caught:
            extract_event(make_email(), client=FakeClient(error=RuntimeError("boom")), now=NOW)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("boom", str(caught.exception))

    def test_reply_without_tool_call(self):
        with self.assertRaises(ExtractionError):
            extract_event(
                make_email(),
                client=FakeClient(blocks=[SimpleNamespace(type="text", text="hi")]),
                now=NOW,
            )

    def test_missing_key_is_a_setup_message(self):
        with patch.object(event_extraction, "_api_key", return_value=""):
            with self.assertRaises(ExtractionError) as caught:
                extract_event(make_email(), now=NOW)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("ANTHROPIC_API_KEY", str(caught.exception))


class EventStoreExtrasTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = user_events.EventStore(Path(directory.name) / "events.json")

    def test_extras_are_stored_and_defaulted(self):
        plain = self.store.create("a", {"title": "Plain", "date": "2026-11-10"})
        self.assertEqual((plain["end_time"], plain["location"], plain["email_id"]), ("", "", ""))
        rich = self.store.create("a", {**GOOD_FIELDS})
        self.assertEqual(rich["location"], "COM1-0210")
        self.assertEqual(rich["email_id"], "msg-1")

    def test_editing_without_extras_keeps_them(self):
        rich = self.store.create("a", {**GOOD_FIELDS})
        updated = self.store.update("a", rich["id"], {"title": "Renamed", "date": "2026-11-14"})
        self.assertEqual(updated["title"], "Renamed")
        self.assertEqual(updated["location"], "COM1-0210")
        self.assertEqual(updated["email_id"], "msg-1")

    def test_editing_can_clear_location(self):
        rich = self.store.create("a", {**GOOD_FIELDS})
        updated = self.store.update(
            "a", rich["id"], {"title": "x", "date": "2026-11-14", "location": ""}
        )
        self.assertEqual(updated["location"], "")

    def test_find_by_email_is_per_owner(self):
        rich = self.store.create("a", {**GOOD_FIELDS})
        self.assertEqual(self.store.find_by_email("a", "msg-1")["id"], rich["id"])
        self.assertIsNone(self.store.find_by_email("b", "msg-1"))
        self.assertIsNone(self.store.find_by_email("a", ""))

    def test_rejects_bad_extras(self):
        for bad in ({"end_time": "9pm"}, {"location": "l" * 201}):
            with self.assertRaises(user_events.EventError):
                self.store.create("a", {"title": "x", "date": "2026-11-10", **bad})


GOOD_FIELDS = {
    "title": "Group meeting",
    "date": "2026-11-13",
    "time": "14:00",
    "end_time": "16:00",
    "location": "COM1-0210",
    "notes": "Finish the report.",
    "email_id": "msg-1",
}


class FromEmailApiTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(
            user_events, "event_store", user_events.EventStore(Path(directory.name) / "e.json")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = create_app(backend="llama", provider="graphtoken").test_client()
        self.payload = {
            "email": {
                "id": "msg-1",
                "subject": "Group meeting",
                "sender": "Alex <alex@u.nus.edu>",
                "received": "2026-11-10T02:00:00+00:00",
                "body": "Friday 2pm at COM1-0210",
            }
        }

    def test_adds_event_once(self):
        with patch("app.server.extract_event", return_value=dict(GOOD_FIELDS)) as extract:
            first = self.client.post("/api/events/from-email", json=self.payload)
            second = self.client.post("/api/events/from-email", json=self.payload)

        self.assertEqual(first.status_code, 201)
        self.assertFalse(first.get_json()["existing"])
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["existing"])
        self.assertEqual(extract.call_count, 1)  # no second Claude call
        events = self.client.get("/api/events").get_json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["email_id"], "msg-1")

    def test_nothing_found_adds_nothing(self):
        with patch("app.server.extract_event", side_effect=ExtractionError("No event here.", 422)):
            response = self.client.post("/api/events/from-email", json=self.payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"], "No event here.")
        self.assertEqual(self.client.get("/api/events").get_json()["events"], [])

    def test_rejects_malformed_requests(self):
        self.assertEqual(self.client.post("/api/events/from-email", json={}).status_code, 400)
        self.assertEqual(
            self.client.post("/api/events/from-email", json={"email": {"subject": "no id"}}).status_code,
            400,
        )

    def test_feed_includes_location_and_end_time(self):
        with patch("app.server.extract_event", return_value=dict(GOOD_FIELDS)):
            self.client.post("/api/events/from-email", json=self.payload)
        link = self.client.get("/api/feed").get_json()["url"]
        ics = self.client.get("/feed/" + link.rsplit("/", 1)[1]).get_data(as_text=True)
        self.assertIn("SUMMARY:Group meeting", ics)
        self.assertIn("LOCATION:COM1-0210", ics)
        self.assertIn("DTSTART:20261113T060000Z", ics)
        self.assertIn("DTEND:20261113T080000Z", ics)  # 14:00-16:00 SGT


if __name__ == "__main__":
    unittest.main()
