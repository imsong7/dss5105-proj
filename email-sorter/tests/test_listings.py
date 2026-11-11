"""Job digests: links kept from HTML, jobs parsed, jobs saved per account."""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app.listings import parse_jobs
from app.pushed_store import pushed_store
from app.server import create_app
from app.text_utils import clean, strip_html, without_link_addresses

BASE = "https://nus-talentconnect.app.kinobi.asia/jobs/"
DIGEST = (
    "Applied Filters:\nJob List: [logo] Singapore General Hospital Research Intern"
    f"<{BASE}1793848831156-6aebf5ffc8a950001da92fb9-research-intern-singapore-general-hospital-sg>"
    " Easy Apply Internship Programme Singapore Remote - Internship Academic Year 2026/2027 Semester 2"
    " (Dec '26 - May/Jun '27) FoS - Semester Undergraduate Professional Internship Programme (UPIP)"
    " SGD 1000 - 1200 (Monthly) [logo] ASTER CHEMICALS AND ENERGY PTE. LTD. ASPIRE: The Aster Graduate"
    f" Programme - Supply Chain<{BASE}1793848428533-6aebf46c39dff7001de8332b-aspire-the-aster-graduate-"
    "programme-supply-chain-aster-chemicals-and-energy-pte-l> Singapore Work from Office - Full time Job"
    " [logo] Synapxe Finance Operation Improvement Project (BIZ)"
    f"<{BASE}1793842335563-6aebdc9f39dff7001de70572-finance-operation-improvement-project-biz-copy-synapxe-sg>"
    " Easy Apply Internship Programme Singapore Hybrid - Internship (Dec '26 - May/Jun '27)"
    " BIZ - (BI3712), min. 24 weeks for Bachelor SGD 1800 - 1800 (Monthly)\n"
    f"View More Jobs <{BASE[:-1]}>"
)


class ParseTests(unittest.TestCase):
    def test_digest_becomes_jobs_with_company_title_and_details(self):
        result = parse_jobs(DIGEST)
        jobs = result["jobs"]

        self.assertEqual(result["more_url"], BASE[:-1])
        self.assertEqual([(j["company"], j["title"]) for j in jobs], [
            ("Singapore General Hospital", "Research Intern"),
            ("Aster Chemicals and Energy Pte. Ltd.", "ASPIRE: The Aster Graduate Programme - Supply Chain"),
            ("Synapxe", "Finance Operation Improvement Project (BIZ)"),
        ])
        first = jobs[0]
        self.assertEqual(
            (first["type"], first["mode"], first["pay"], first["period"], first["programme"], first["easy_apply"]),
            ("Internship", "Remote", "SGD 1,000–1,200/mo", "Dec '26 - May/Jun '27", "UPIP", True),
        )
        self.assertEqual((jobs[1]["type"], jobs[1]["mode"], jobs[1]["pay"]), ("Full time", "Office", ""))
        self.assertEqual((jobs[2]["pay"], jobs[2]["programme"]), ("SGD 1,800/mo", "BI3712"))

    def test_other_mail_has_no_jobs(self):
        self.assertIsNone(parse_jobs("Assignment 1 due Friday <https://canvas.nus.edu.sg/x>"))


class LinkTextTests(unittest.TestCase):
    def test_html_links_keep_their_address_and_safe_links_are_unwrapped(self):
        html = (
            '<p><a href="https://nam11.safelinks.protection.outlook.com/?url=https%3A%2F%2Fexample.org%2Fjob'
            '&amp;data=1"><b>Research Intern</b></a> Easy Apply</p><a href="https://x.org"><img alt="logo"></a>'
        )
        text = clean(strip_html(html))
        self.assertIn("Research Intern <https://example.org/job>", text)
        self.assertNotIn("x.org", text)  # an image-only link adds nothing

    def test_addresses_are_dropped_for_the_model(self):
        self.assertEqual(without_link_addresses("Open<https://a.b/c> now"), "Open now")


class SavedJobsApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "multiuser.json"
        path.write_text(json.dumps({
            email: {"password_hash": generate_password_hash("pw-12345678"), "webhook_token": token, "refresh_url": ""}
            for email, token in (("a@u.nus.edu", "a" * 43), ("b@u.nus.edu", "b" * 43))
        }), encoding="utf-8")
        env = patch.dict(os.environ, {"MULTIUSER_CONFIG_FILE": str(path), "SESSION_SECRET": "s"})
        env.start()
        self.addCleanup(env.stop)
        pushed_store.clear()
        self.addCleanup(pushed_store.clear)
        self.app = create_app(backend="llama", provider="powerautomate")

    def client_for(self, email):
        client = self.app.test_client()
        page = client.get("/login").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        client.post("/login", data={"email": email, "password": "pw-12345678", "csrf_token": csrf, "next": "/"})
        return client

    def test_digest_mail_comes_with_its_jobs(self):
        self.app.test_client().post(
            "/api/inbound/outlook",
            json={"internetMessageId": "d1", "subject": "Jobs for you", "body": DIGEST, "from": "talentconnect@nus.edu.sg"},
            headers={"X-Webhook-Token": "a" * 43},
        )
        email = self.client_for("a@u.nus.edu").post(
            "/api/emails", json={"provider": "powerautomate", "count": 5}
        ).get_json()["emails"][0]
        self.assertEqual(len(email["jobs"]["jobs"]), 3)

    def test_jobs_are_saved_listed_and_removed_per_account(self):
        alice, bob = self.client_for("a@u.nus.edu"), self.client_for("b@u.nus.edu")
        job = parse_jobs(DIGEST)["jobs"][0]

        self.assertEqual(alice.post("/api/saved-jobs", json=job).status_code, 200)
        self.assertEqual(alice.post("/api/saved-jobs", json=job).status_code, 200)  # saving twice keeps one
        self.assertEqual([j["title"] for j in alice.get("/api/saved-jobs").get_json()["jobs"]], ["Research Intern"])
        self.assertEqual(bob.get("/api/saved-jobs").get_json()["jobs"], [])
        self.assertEqual(alice.post("/api/saved-jobs", json={**job, "url": "javascript:alert(1)"}).status_code, 400)

        self.assertEqual(bob.delete(f"/api/saved-jobs/{job['id']}").status_code, 404)
        self.assertEqual(alice.delete(f"/api/saved-jobs/{job['id']}").status_code, 200)
        self.assertEqual(alice.get("/api/saved-jobs").get_json()["jobs"], [])


if __name__ == "__main__":
    unittest.main()
