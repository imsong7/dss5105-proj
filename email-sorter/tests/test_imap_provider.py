import unittest
from email.message import EmailMessage
from unittest.mock import patch

from app.models import Email
from app.providers.imap import ImapProvider


class FakeImap:
    def __init__(self, message):
        self.message = message
        self.selected = None

    def login(self, user, password):
        return "OK", []

    def select(self, folder, readonly=True):
        self.selected = (folder, readonly)
        return "OK", []

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


if __name__ == "__main__":
    unittest.main()
