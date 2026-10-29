import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from unittest.mock import patch

from app.models import Email
from app.providers.base import MailQuery
from app.providers.imap import ImapProvider


class FakeImap:
    def __init__(self, message):
        self.message = message
        self.selected = None
        self.search_args = None

    def login(self, user, password):
        return "OK", []

    def select(self, folder, readonly=True):
        self.selected = (folder, readonly)
        return "OK", []

    def search(self, charset, *criteria):
        self.search_args = (charset, criteria)
        return "OK", [b""]

    def fetch(self, message_id, query):
        return "OK", [(b"message", self.message.as_bytes())]

    def logout(self):
        return "BYE", []


class ImapInlineImageTests(unittest.TestCase):
    @patch("app.providers.imap.imaplib.IMAP4_SSL")
    def test_reads_inline_image_but_skips_regular_attachment(self, imap_ssl):
        message = EmailMessage()
        message.set_content("short body")
        message.add_alternative("<p>Poster</p>", subtype="html")
        html = message.get_payload()[1]
        html.add_related(
            b"inline-image-bytes",
            maintype="image",
            subtype="png",
            cid="<inline-id>",
            filename="poster.png",
        )
        message.add_attachment(
            b"attached-image-bytes",
            maintype="image",
            subtype="png",
            filename="attachment.png",
        )
        imap_ssl.return_value = FakeImap(message)

        provider = ImapProvider("imap.example.com", "user", "password")
        images = provider.fetch_images(
            Email(id="12"), max_images=3, max_bytes=100
        )

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].name, "poster.png")
        self.assertEqual(images[0].data, b"inline-image-bytes")
        self.assertEqual(imap_ssl.return_value.selected, ("INBOX", True))


class ImapFetchWindowTests(unittest.TestCase):
    @patch("app.providers.imap.imaplib.IMAP4_SSL")
    def test_search_uses_inclusive_date_window(self, imap_ssl):
        fake = FakeImap(EmailMessage())
        imap_ssl.return_value = fake

        ImapProvider("imap.example.com", "user", "password").fetch_emails(
            MailQuery(
                limit=10,
                since=datetime(2026, 9, 1, tzinfo=timezone.utc),
                before=datetime(2026, 11, 13, 23, 59, 59, tzinfo=timezone.utc),
            )
        )

        # IMAP has day precision, so "before" is pushed to the next day.
        self.assertEqual(
            fake.search_args[1],
            ("SINCE", "01-Sep-2026", "BEFORE", "14-Nov-2026"),
        )

    @patch("app.providers.imap.imaplib.IMAP4_SSL")
    def test_search_defaults_to_all_when_no_window(self, imap_ssl):
        fake = FakeImap(EmailMessage())
        imap_ssl.return_value = fake

        ImapProvider("imap.example.com", "user", "password").fetch_emails()

        self.assertEqual(fake.search_args[1], ("ALL",))


if __name__ == "__main__":
    unittest.main()
