import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.schemas import Email
from app.server import create_app


class CapturingProvider:
    def __init__(self):
        self.query = None

    def fetch_emails(self, query=None):
        self.query = query
        return [Email(id="1", received="2026-10-01T00:00:00Z")]

    def fetch_images(self, email, max_images, max_bytes):
        return []


class EmailWindowApiTests(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "app.server.prepare_text",
            side_effect=lambda email, _provider: email,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, payload):
        return create_app(backend="llama").test_client().post("/api/emails", json=payload)

    @patch("app.server.build_provider")
    def test_forwards_window_as_mail_query(self, build_provider):
        provider = CapturingProvider()
        build_provider.return_value = provider

        response = self._post(
            {
                "provider": "outlook",
                "credentials": {"token": "test"},
                "count": 5,
                "since": "2026-09-01T00:00:00Z",
                "before": "2026-11-13T23:59:59+08:00",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.query.limit, 5)
        self.assertEqual(
            provider.query.since, datetime(2026, 9, 1, tzinfo=timezone.utc)
        )
        self.assertEqual(
            provider.query.before,
            datetime(2026, 11, 13, 15, 59, 59, tzinfo=timezone.utc),
        )
        self.assertEqual(response.get_json()["window"]["limit"], 5)

    @patch("app.server.build_provider")
    def test_no_window_keeps_newest_n_behaviour(self, build_provider):
        provider = CapturingProvider()
        build_provider.return_value = provider

        response = self._post(
            {"provider": "outlook", "credentials": {"token": "test"}, "count": 3}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.query.limit, 3)
        self.assertIsNone(provider.query.since)
        self.assertIsNone(provider.query.before)

    def test_invalid_date_is_rejected(self):
        response = self._post(
            {
                "provider": "outlook",
                "credentials": {"token": "test"},
                "since": "last tuesday",
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ISO 8601", response.get_json()["error"])

    def test_reversed_window_is_rejected(self):
        response = self._post(
            {
                "provider": "outlook",
                "credentials": {"token": "test"},
                "since": "2026-11-13T00:00:00Z",
                "before": "2026-09-01T00:00:00Z",
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("earlier", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
