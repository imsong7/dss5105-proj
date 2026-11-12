"""The "open in Outlook" link on each email (app/mail/text_utils.outlook_link)."""

import unittest

from app.mail.flow_package import _definition
from app.mail.providers.graph import message_to_email as graph_email
from app.mail.text_utils import outlook_link
from app.routes.inbound import inbound_email


class OutlookLinkTests(unittest.TestCase):
    def test_microsofts_own_weblink_is_kept(self):
        link = "https://outlook.office365.com/owa/?ItemID=AAMk%3D&exvsurl=1&viewmodel=ReadMessageItem"
        self.assertEqual(outlook_link(link, ""), link)

    def test_built_from_the_outlook_item_id(self):
        self.assertEqual(
            outlook_link("", "AAMkAD/x+y="),
            "https://outlook.office365.com/owa/?ItemID=AAMkAD%2Fx%2By%3D&exvsurl=1&viewmodel=ReadMessageItem",
        )

    def test_never_links_anywhere_but_outlook(self):
        self.assertEqual(outlook_link("https://evil.example.com/owa/?ItemID=1", ""), "")
        self.assertEqual(outlook_link("http://outlook.office365.com/owa/", ""), "")  # not https
        self.assertEqual(outlook_link("javascript:alert(1)", ""), "")

    def test_an_internet_message_id_cannot_be_opened(self):
        self.assertEqual(outlook_link("", "<abc@example.com>"), "")
        self.assertEqual(outlook_link("", ""), "")


class EmailSourcesTests(unittest.TestCase):
    def test_pushed_mail_carries_the_link(self):
        email = inbound_email({"internetMessageId": "<m@x>", "subject": "Hi", "body": "b", "outlookId": "AAMk1"})
        self.assertIn("ItemID=AAMk1", email.web_link)
        self.assertEqual(inbound_email({"internetMessageId": "<m@x>", "body": "b"}).web_link, "")

    def test_graph_mail_carries_the_link(self):
        email = graph_email({"id": "AAMk2", "subject": "Hi", "body": {"content": "b"}})
        self.assertIn("ItemID=AAMk2", email.web_link)

    def test_the_flow_sends_the_outlook_id(self):
        actions = _definition("https://x/api/inbound/outlook", "a@u.nus.edu", "t" * 43)["properties"]["definition"]["actions"]
        body = actions["Send_each_email"]["actions"]["HTTP"]["inputs"]["body"]
        self.assertEqual(body["outlookId"], "@{item()?['id']}")


if __name__ == "__main__":
    unittest.main()
