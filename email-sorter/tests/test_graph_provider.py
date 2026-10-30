import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from app.schemas import Email
from app.providers.graph import GRAPH_URL, GraphProvider
from app.providers.base import MailQuery, ProviderError


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

    @patch("app.providers.graph.requests.get")
    def test_fetch_applies_inclusive_received_window(self, get):
        get.return_value.ok = True
        get.return_value.json.return_value = {"value": []}
        provider = GraphProvider("test-token")

        provider.fetch_emails(
            MailQuery(
                limit=5,
                since=datetime(2026, 9, 1, tzinfo=timezone.utc),
                before=datetime(2026, 11, 13, 23, 59, 59, tzinfo=timezone.utc),
            )
        )

        params = get.call_args.kwargs["params"]
        self.assertEqual(params["$top"], 5)
        self.assertEqual(
            params["$filter"],
            "receivedDateTime ge 2026-09-01T00:00:00Z and "
            "receivedDateTime le 2026-11-13T23:59:59Z",
        )

    @patch("app.providers.graph.requests.get")
    def test_fetch_without_window_omits_filter(self, get):
        get.return_value.ok = True
        get.return_value.json.return_value = {"value": []}

        GraphProvider("test-token").fetch_emails()

        params = get.call_args.kwargs["params"]
        self.assertNotIn("$filter", params)
        self.assertEqual(params["$top"], 15)

    @patch("app.providers.graph.requests.get")
    def test_fetches_only_small_inline_images(self, get):
        image_bytes = b"small-image"
        metadata_response = Mock()
        metadata_response.status_code = 200
        metadata_response.ok = True
        metadata_response.json.return_value = {
            "value": [
                {
                    "id": "inline-id",
                    "name": "inline.png",
                    "contentType": "image/png",
                    "size": len(image_bytes),
                    "isInline": True,
                },
                {
                    "id": "file-id",
                    "name": "attachment.png",
                    "contentType": "image/png",
                    "size": len(image_bytes),
                    "isInline": False,
                },
                {
                    "id": "large-id",
                    "name": "large.png",
                    "contentType": "image/png",
                    "size": 999,
                    "isInline": True,
                },
            ]
        }
        content_response = Mock()
        content_response.status_code = 200
        content_response.ok = True
        content_response.content = image_bytes
        get.side_effect = [metadata_response, content_response]

        images = GraphProvider("test-token").fetch_images(
            Email(id="message/1"), max_images=3, max_bytes=100
        )

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].name, "inline.png")
        self.assertEqual(images[0].data, image_bytes)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(
            get.call_args.args[0],
            f"{GRAPH_URL}/message%2F1/attachments/inline-id/$value",
        )
        self.assertEqual(
            get.call_args_list[0].kwargs["params"]["$select"],
            "id,name,contentType,size,isInline",
        )

    @patch("app.providers.graph.requests.get")
    def test_attachment_listing_includes_graph_error_detail(self, get):
        response = Mock()
        response.status_code = 400
        response.ok = False
        response.json.return_value = {
            "error": {"message": "Invalid filter clause"}
        }
        get.return_value = response

        with self.assertRaisesRegex(ProviderError, "Invalid filter clause"):
            GraphProvider("test-token").fetch_images(
                Email(id="message-1"), max_images=2, max_bytes=100
            )


if __name__ == "__main__":
    unittest.main()
