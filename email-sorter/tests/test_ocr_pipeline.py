import io
import unittest
from unittest.mock import patch

from PIL import Image

from app.models import Email
from app.ocr_pipeline import prepare_text
from app.providers.base import EmailProvider, InlineImage
from app.server import create_app


def sample_png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (120, 100), "white").save(output, format="PNG")
    return output.getvalue()


class InlineImageProvider(EmailProvider):
    name = "test"

    def __init__(self):
        self.images_requested = 0

    def fetch_emails(self, limit=15):
        return [Email(id="image-email", subject="Poster")]

    def fetch_images(self, email, max_images, max_bytes):
        self.images_requested += 1
        return [InlineImage("poster.png", sample_png())]


class OcrPipelineTests(unittest.TestCase):
    @patch("app.ocr_pipeline.read_image", return_value=("Submit the form by Friday", 82.5))
    @patch("app.ocr_pipeline.find_tesseract", return_value="/usr/bin/tesseract")
    @patch("app.ocr_pipeline.OCR_ENABLED", True)
    def test_extracts_inline_image_text_and_metadata(self, _command, _ocr):
        provider = InlineImageProvider()
        email = prepare_text(Email(id="1"), provider)

        self.assertIn("Submit the form by Friday", email.body)
        self.assertEqual(email.text_source, "ocr")
        self.assertEqual(email.ocr_confidence, 82.5)
        self.assertEqual(provider.images_requested, 1)

    @patch("app.ocr_pipeline.find_tesseract", return_value=None)
    @patch("app.ocr_pipeline.OCR_ENABLED", True)
    def test_reports_missing_tesseract_without_failing(self, _command):
        email = prepare_text(Email(id="1"), InlineImageProvider())

        self.assertEqual(email.text_source, "empty")
        self.assertTrue(any("Tesseract is not installed" in note for note in email.ocr_notes))

    @patch("app.ocr_pipeline.read_image", return_value=("Image text extracted", 90.0))
    @patch("app.ocr_pipeline.find_tesseract", return_value="/usr/bin/tesseract")
    @patch("app.ocr_pipeline.OCR_ENABLED", True)
    @patch("app.server.build_provider")
    def test_email_fetch_route_runs_ocr_before_returning(
        self, build_provider, _command, _ocr
    ):
        provider = InlineImageProvider()
        build_provider.return_value = provider
        client = create_app(backend="llama").test_client()

        response = client.post(
            "/api/emails",
            json={"provider": "outlook", "credentials": {"token": "test"}, "count": 1},
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()["emails"][0]
        self.assertIn("Image text extracted", result["body"])
        self.assertEqual(result["text_source"], "ocr")
        self.assertEqual(provider.images_requested, 1)


if __name__ == "__main__":
    unittest.main()
