import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import user_events
from app.server import create_app


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = user_events.EventStore(Path(self.directory.name) / "events.json")

    def test_create_list_update_delete(self):
        event = self.store.create("a@u.nus.edu", {"title": " Study ", "date": "2026-11-10", "time": "14:30"})
        self.assertEqual(event["title"], "Study")
        self.assertEqual(self.store.list("a@u.nus.edu"), [event])

        updated = self.store.update("a@u.nus.edu", event["id"], {"title": "Group call", "date": "2026-11-11"})
        self.assertEqual(updated["title"], "Group call")
        self.assertEqual(updated["time"], "")

        self.assertTrue(self.store.delete("a@u.nus.edu", event["id"]))
        self.assertEqual(self.store.list("a@u.nus.edu"), [])
        self.assertFalse(self.store.delete("a@u.nus.edu", event["id"]))

    def test_events_are_private_per_owner(self):
        event = self.store.create("a@u.nus.edu", {"title": "Mine", "date": "2026-11-10"})
        self.assertEqual(self.store.list("b@u.nus.edu"), [])
        self.assertIsNone(self.store.update("b@u.nus.edu", event["id"], {"title": "x", "date": "2026-11-10"}))
        self.assertFalse(self.store.delete("b@u.nus.edu", event["id"]))
        self.assertEqual(len(self.store.list("a@u.nus.edu")), 1)

    def test_rejects_bad_input(self):
        for bad in (
            {"title": "", "date": "2026-11-10"},
            {"title": "x", "date": "2026-13-40"},
            {"title": "x", "date": "2026-11-10", "time": "25:00"},
            {"title": "x" * 121, "date": "2026-11-10"},
            {"title": "x", "date": "2026-11-10", "notes": "n" * 501},
            "not an object",
        ):
            with self.assertRaises(user_events.EventError, msg=bad):
                self.store.create("a@u.nus.edu", bad)

    def test_limit_per_owner(self):
        with patch.object(user_events, "MAX_EVENTS_PER_OWNER", 2):
            self.store.create("a", {"title": "1", "date": "2026-11-10"})
            self.store.create("a", {"title": "2", "date": "2026-11-10"})
            with self.assertRaises(user_events.EventError):
                self.store.create("a", {"title": "3", "date": "2026-11-10"})


class EventApiTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(
            user_events, "event_store", user_events.EventStore(Path(directory.name) / "e.json")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = create_app(backend="llama", provider="graphtoken").test_client()

    def test_round_trip(self):
        created = self.client.post("/api/events", json={"title": "Quiz prep", "date": "2026-11-12"})
        self.assertEqual(created.status_code, 201)
        event_id = created.get_json()["id"]

        listed = self.client.get("/api/events").get_json()["events"]
        self.assertEqual([e["id"] for e in listed], [event_id])

        edited = self.client.put(f"/api/events/{event_id}", json={"title": "Quiz", "date": "2026-11-13"})
        self.assertEqual(edited.get_json()["date"], "2026-11-13")

        self.assertEqual(self.client.delete(f"/api/events/{event_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/events/{event_id}").status_code, 404)

    def test_validation_error_is_400(self):
        response = self.client.post("/api/events", json={"title": "", "date": "2026-11-12"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.get_json()["error"])
