"""Posters in emails: facts from OCR text, QR links, previews, pushed images."""

import base64
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.security import generate_password_hash

from app.extract import poster
from app.mail.flow_package import _definition
from app.extract.ocr import prepare_text
from app.mail.providers.pushed import PushedProvider
from app.mail.pushed_store import pushed_images, pushed_store
from app.schemas import Email
from app.server import create_app

OCR_TEXT = """CAREER FAIR 2026
Meet Grab, Shopee and DBS
Wednesday, 18 Nov 2026 | 2pm - 5pm
Venue: MPSH 2, Kent Ridge
Register at go.gov.sg/nus-fair"""


def png(width=400, height=500, colour="white") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, format="PNG")
    return out.getvalue()


def qr_png(text: str) -> bytes:
    import cv2
    import numpy as np

    matrix = cv2.QRCodeEncoder.create().encode(text)
    img = Image.fromarray(np.array(matrix, dtype="uint8")).resize((300, 300), Image.NEAREST)
    canvas = Image.new("L", (420, 420), 255)
    canvas.paste(img, (60, 60))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


class FactsTests(unittest.TestCase):
    def test_title_date_time_venue_and_link_come_out_of_poster_text(self):
        facts = poster.facts_from_text(OCR_TEXT, "2026-11-10T08:00:00+00:00")

        self.assertEqual(facts["title"], "CAREER FAIR 2026")
        self.assertEqual(facts["when"]["date"], "2026-11-18")
        self.assertEqual(facts["when"]["time"], "2pm - 5pm")
        self.assertEqual(facts["venue"], "MPSH 2, Kent Ridge")
        self.assertEqual(facts["links"], ["https://go.gov.sg/nus-fair"])

    def test_a_date_without_year_is_placed_after_the_email_arrived(self):
        when = poster.find_when("Talk on 5 Jan, 7pm", "2026-12-20T00:00:00Z")
        self.assertEqual(when["date"], "2027-01-05")
        self.assertTrue(when["year_inferred"])

    def test_venue_found_by_known_place_names_without_a_label(self):
        self.assertEqual(poster.find_venue(["Join us", "LT27, Faculty of Science"]), "LT27, Faculty of Science")


class QrTests(unittest.TestCase):
    def test_qr_code_link_is_read_from_the_image(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV not installed")
        self.assertEqual(poster.decode_qr(qr_png("https://forms.gle/abc123")), ["https://forms.gle/abc123"])

    def test_plain_image_has_no_links(self):
        self.assertEqual(poster.decode_qr(png()), [])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        pushed_store.clear()
        pushed_images.clear()
        poster.thumbs.clear()
        self.addCleanup(pushed_store.clear)
        self.addCleanup(pushed_images.clear)
        self.addCleanup(poster.thumbs.clear)

    def test_pushed_poster_becomes_facts_and_a_preview_once(self):
        email = Email(id="m1", subject="Career fair", received="2026-11-10T08:00:00Z", body="")
        pushed_store.add(email, "a@u.nus.edu")
        pushed_images.put("a@u.nus.edu", "m1", [("poster.png", png())])
        provider = PushedProvider("a@u.nus.edu")

        with patch("app.extract.ocr.find_tesseract", return_value="tesseract"), patch(
            "app.extract.ocr.read_image", return_value=(OCR_TEXT, 88.0)
        ) as read:
            prepare_text(email, provider, "a@u.nus.edu")
            prepare_text(email, provider, "a@u.nus.edu")  # the next poll

        self.assertEqual(read.call_count, 1)
        self.assertIn("CAREER FAIR", email.ocr_text)
        self.assertEqual(email.poster["title"], "CAREER FAIR 2026")
        self.assertEqual(email.poster["when"]["date"], "2026-11-18")
        self.assertTrue(email.poster["has_image"])
        self.assertIsNotNone(poster.thumbs.get("a@u.nus.edu", "m1"))
        self.assertEqual(pushed_images.get("a@u.nus.edu", "m1"), [])  # bytes freed

    def test_long_text_email_still_gets_its_poster_qr_link(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV not installed")
        email = Email(id="m2", subject="Talk", body="x" * 300)
        pushed_images.put("a@u.nus.edu", "m2", [("qr.png", qr_png("https://forms.gle/xyz"))])

        prepare_text(email, PushedProvider("a@u.nus.edu"), "a@u.nus.edu")

        self.assertEqual(email.poster["links"], [{"url": "https://forms.gle/xyz", "source": "qr"}])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "multiuser.json"
        accounts = {
            email: {"password_hash": generate_password_hash("pw-12345678"), "webhook_token": token, "refresh_url": ""}
            for email, token in (("a@u.nus.edu", "a" * 43), ("b@u.nus.edu", "b" * 43))
        }
        path.write_text(json.dumps(accounts), encoding="utf-8")
        env = patch.dict(os.environ, {"MULTIUSER_CONFIG_FILE": str(path), "SESSION_SECRET": "s"})
        env.start()
        self.addCleanup(env.stop)
        for store in (pushed_store, pushed_images, poster.thumbs):
            store.clear()
            self.addCleanup(store.clear)
        self.app = create_app(backend="llama", provider="powerautomate")

    def client_for(self, email):
        client = self.app.test_client()
        page = client.get("/login").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        client.post("/login", data={"email": email, "password": "pw-12345678", "csrf_token": csrf, "next": "/"})
        return client

    def test_webhook_keeps_images_and_preview_is_private_to_the_owner(self):
        image = base64.b64encode(png()).decode()
        pushed = self.app.test_client().post(
            "/api/inbound/outlook",
            json={
                "internetMessageId": "<p1@x>", "subject": "Fair", "body": "", "from": "c@nus.edu.sg",
                "receivedDateTime": "2026-11-10T08:00:00Z",
                "inlineImages": [
                    {"name": "poster.png", "contentType": "image/png", "contentBytes": image, "isInline": True},
                    {"name": "file.pdf", "contentType": "application/pdf", "contentBytes": image},
                ],
            },
            headers={"X-Webhook-Token": "a" * 43},
        )
        self.assertEqual(pushed.status_code, 200)
        self.assertEqual([name for name, _ in pushed_images.get("a@u.nus.edu", "<p1@x>")], ["poster.png"])

        owner = self.client_for("a@u.nus.edu")
        with patch("app.extract.ocr.find_tesseract", return_value="tesseract"), patch(
            "app.extract.ocr.read_image", return_value=(OCR_TEXT, 90.0)
        ):
            data = owner.post("/api/emails", json={"provider": "powerautomate", "count": 10}).get_json()
        email = data["emails"][0]
        self.assertEqual(email["poster"]["venue"], "MPSH 2, Kent Ridge")
        self.assertTrue(email["deadline_candidates"] == [] or "from_image" in email["deadline_candidates"][0])

        url = "/api/emails/%3Cp1%40x%3E/poster.jpg"
        self.assertEqual(owner.get(url).mimetype, "image/jpeg")
        self.assertEqual(self.client_for("b@u.nus.edu").get(url).status_code, 404)


def _flat():
    with patch("app.mail.flow_package.BATCHES", 1):
        return _definition("https://x/api/inbound/outlook", "a@u.nus.edu", "t" * 43)["properties"]["definition"]


class FlowTests(unittest.TestCase):
    def test_flow_sends_only_small_images_with_each_email(self):
        with patch("app.mail.flow_package.INCLUDE_IMAGES", True):
            self._check_image_flow()

    def test_flow_can_skip_images(self):
        with patch("app.mail.flow_package.INCLUDE_IMAGES", False):
            self._check_no_image_flow()

    def _check_no_image_flow(self):
        flow = _flat()
        actions = flow["actions"]
        self.assertFalse(actions["Get_emails_(V3)"]["inputs"]["parameters"]["includeAttachments"])
        loop = actions["Send_each_email"]["actions"]
        self.assertNotIn("Inline_images", loop)
        self.assertNotIn("inlineImages", loop["HTTP"]["inputs"]["body"])
        self.assertNotIn("runAfter", loop["HTTP"])

    def _check_image_flow(self):
        flow = _flat()
        actions = flow["actions"]
        self.assertTrue(actions["Get_emails_(V3)"]["inputs"]["parameters"]["includeAttachments"])
        loop = actions["Send_each_email"]["actions"]
        self.assertEqual(loop["Inline_images"]["type"], "Query")
        self.assertIn("image/", loop["Inline_images"]["inputs"]["where"])
        self.assertEqual(loop["HTTP"]["inputs"]["body"]["inlineImages"], "@take(body('Inline_images'), 1)")

    def test_flow_settings_are_tunable(self):
        with patch("app.mail.flow_package.TOP", 300), patch("app.mail.flow_package.DEFAULT_DAYS", 90), patch(
            "app.mail.flow_package.FOREACH_PARALLEL", 5
        ):
            flow = _flat()
        get = flow["actions"]["Get_emails_(V3)"]["inputs"]["parameters"]
        self.assertEqual(get["top"], "@coalesce(triggerBody()?['top'], 300)")
        self.assertIn("addDays(utcNow(), -90)", get["searchQuery"])
        self.assertEqual(flow["actions"]["Send_each_email"]["runtimeConfiguration"]["concurrency"]["repetitions"], 5)


    def test_flow_reads_date_slices_in_parallel(self):
        flow = _definition("https://x/api/inbound/outlook", "a@u.nus.edu", "t" * 43)["properties"]["definition"]
        batch = flow["actions"]["Each_batch"]
        self.assertEqual(batch["foreach"], "@createArray(0, 1, 2)")
        self.assertEqual(batch["runtimeConfiguration"]["concurrency"]["repetitions"], 3)
        get = batch["actions"]["Get_emails_(V3)"]["inputs"]["parameters"]
        self.assertEqual(get["top"], "@div(coalesce(triggerBody()?['top'], 300), 3)")
        self.assertIn("received>=", get["searchQuery"])
        self.assertIn("received<", get["searchQuery"])
        self.assertIn("Send_each_email", batch["actions"])


if __name__ == "__main__":
    unittest.main()
