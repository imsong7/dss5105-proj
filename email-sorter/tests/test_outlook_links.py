import unittest
from unittest.mock import Mock, patch

from app.outlook_links import outlook_link
from app.providers.graph import GraphProvider, message_to_email
from app.schemas import Email
from app.server import _inbound_email


class OutlookLinkTests(unittest.TestCase):
    def test_graph_web_link_is_used(self):
        url = "https://outlook.office365.com/owa/?ItemID=AAMk%3D&exvsurl=1&viewmodel=ReadMessageItem"
        link = outlook_link(Email(id="1", web_link=url))
        self.assertEqual(link, {"url": url, "exact": True})

    def test_link_is_built_from_outlook_id(self):
        link = outlook_link(Email(id="<rfc@x>", outlook_id="AAMkAD/abc+="))
        self.assertTrue(link["exact"])
        self.assertIn("ItemID=AAMkAD%2Fabc%2B%3D", link["url"])
        self.assertTrue(link["url"].startswith("https://outlook.office.com/owa/"))

    def test_rfc_message_id_is_never_used_as_outlook_id(self):
        link = outlook_link(Email(id="<rfc@x>", outlook_id="<rfc@x>"))
        self.assertFalse(link["exact"])

    def test_inbox_fallback_with_and_without_a_sign_in_hint(self):
        self.assertEqual(
            outlook_link(Email(id="1"), "me@u.nus.edu"),
            {"url": "https://outlook.office.com/mail/?login_hint=me%40u.nus.edu", "exact": False},
        )
        self.assertEqual(
            outlook_link(Email(id="1")), {"url": "https://outlook.office.com/mail/", "exact": False}
        )

    def test_pushed_links_to_other_sites_are_ignored(self):
        for bad in (
            "https://evil.example/owa/?ItemID=1",
            "http://outlook.office.com/owa/",
            "https://outlook.office.com.evil.example/x",
            "javascript:alert(1)",
        ):
            link = outlook_link(Email(id="1", web_link=bad))
            self.assertFalse(link["exact"], bad)
            self.assertNotIn("evil", link["url"])


class GraphProviderLinkTests(unittest.TestCase):
    def test_message_keeps_web_link_and_id(self):
        email = message_to_email({
            "id": "AAMk1",
            "subject": "Hi",
            "webLink": "https://outlook.office365.com/owa/?ItemID=AAMk1",
            "body": {"content": "text"},
        })
        self.assertEqual(email.web_link, "https://outlook.office365.com/owa/?ItemID=AAMk1")
        self.assertEqual(email.outlook_id, "AAMk1")

    @patch("app.providers.graph.requests.get")
    def test_fetch_asks_graph_for_web_link(self, get):
        response = Mock(status_code=200, ok=True)
        response.json.return_value = {"value": []}
        get.return_value = response
        GraphProvider("token").fetch_emails()
        self.assertIn("webLink", get.call_args.kwargs["params"]["$select"].split(","))


class PushedMailLinkTests(unittest.TestCase):
    def test_flow_that_sends_both_ids_keeps_both(self):
        email = _inbound_email({
            "internetMessageId": "<rfc@example.com>",
            "id": "AAMk-graph-id",
            "webLink": "https://outlook.office365.com/owa/?ItemID=AAMk-graph-id",
            "subject": "Hi",
            "body": "text",
        })
        self.assertEqual(email.id, "<rfc@example.com>")
        self.assertEqual(email.outlook_id, "AAMk-graph-id")
        self.assertTrue(outlook_link(email)["exact"])

    def test_old_flow_without_ids_falls_back_to_inbox(self):
        email = _inbound_email({"internetMessageId": "<rfc@example.com>", "subject": "Hi", "body": "t"})
        self.assertEqual(email.outlook_id, "")
        self.assertFalse(outlook_link(email)["exact"])

    def test_empty_flow_expressions_are_ignored(self):
        email = _inbound_email({
            "internetMessageId": "<rfc@example.com>", "id": "", "webLink": "", "subject": "Hi", "body": "t",
        })
        self.assertEqual((email.outlook_id, email.web_link), ("", ""))


if __name__ == "__main__":
    unittest.main()
