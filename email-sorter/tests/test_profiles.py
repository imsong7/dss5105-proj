import unittest

from app import profiles
from app.server import create_app


class ProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(backend="llama", provider="graphtoken").test_client()

    def test_name_round_trip_and_clear(self):
        self.assertEqual(self.client.get("/api/session").get_json()["name"], "")

        response = self.client.post("/api/profile", json={"name": "  Soo   Yeon "})
        self.assertEqual(response.get_json()["name"], "Soo Yeon")
        self.assertEqual(self.client.get("/api/session").get_json()["name"], "Soo Yeon")

        self.client.post("/api/profile", json={"name": ""})
        self.assertEqual(self.client.get("/api/session").get_json()["name"], "")

    def test_rejects_long_or_control_names(self):
        for bad in ("x" * 41, "bad\x07name"):
            response = self.client.post("/api/profile", json={"name": bad})
            self.assertEqual(response.status_code, 400)

    def test_clean_name_collapses_spaces(self):
        self.assertEqual(profiles.clean_name("  a   b "), "a b")
