import tempfile
import unittest
from pathlib import Path

from app.stores import item_states as module
from app.server import create_app


class ItemStateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = module.ItemStateStore(Path(directory.name) / "s.json")

    def test_done_snooze_and_clear(self):
        self.store.set("a", {"key": "m1", "done": True})
        self.store.set("a", {"key": "m2", "snoozed_until": "2026-11-10"})
        states = self.store.list("a")
        self.assertTrue(states["m1"]["done"])
        self.assertEqual(states["m2"]["snoozed_until"], "2026-11-10")

        self.assertIsNone(self.store.set("a", {"key": "m1", "done": False}))
        self.assertNotIn("m1", self.store.list("a"))

    def test_in_calendar_mark_is_kept_on_its_own_and_with_done(self):
        self.store.set("a", {"key": "m1", "in_calendar": True})
        self.assertTrue(self.store.list("a")["m1"]["in_calendar"])
        # Marking it done keeps it in the calendar when the client sends both.
        self.store.set("a", {"key": "m1", "done": True, "in_calendar": True})
        self.assertEqual(
            (self.store.list("a")["m1"]["done"], self.store.list("a")["m1"]["in_calendar"]), (True, True)
        )
        self.assertIsNone(self.store.set("a", {"key": "m1"}))  # nothing left: the record goes

    def test_private_per_owner(self):
        self.store.set("a", {"key": "m1", "done": True})
        self.assertEqual(self.store.list("b"), {})

    def test_rejects_bad_input(self):
        for bad in ({"done": True}, {"key": "k", "snoozed_until": "soon"}, "x"):
            with self.assertRaises(module.StateError):
                self.store.set("a", bad)


class ItemStateApiTests(unittest.TestCase):
    def test_round_trip(self):
        client = create_app(backend="llama", provider="graphtoken").test_client()
        response = client.post("/api/item-states", json={"key": "event:abc/1", "done": True})
        self.assertEqual(response.status_code, 200)
        states = client.get("/api/item-states").get_json()["states"]
        self.assertTrue(states["event:abc/1"]["done"])
        self.assertEqual(client.post("/api/item-states", json={"done": True}).status_code, 400)
