import unittest
from unittest.mock import patch

from app.providers.graph import GraphProvider


class GraphProviderTests(unittest.TestCase):
    @patch("app.providers.graph.requests.get")
    def test_fetch_sends_bearer_token(self, get):
        get.return_value.ok = True
        get.return_value.json.return_value = {"value": []}
        provider = GraphProvider("test-token")

        provider.fetch_emails()

        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-token",
        )

    def test_strips_bearer_prefix_from_token(self):
        provider = GraphProvider("Bearer test-token")

        self.assertEqual(provider.token, "test-token")


if __name__ == "__main__":
    unittest.main()
