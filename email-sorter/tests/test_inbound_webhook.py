"""Tests for pushed mail under the per-account multi-user model."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from werkzeug.security import generate_password_hash

from app.pushed_store import PushedStore, pushed_store
from app.schemas import Email
from app.providers import build_provider
from app.providers.base import MailQuery
from app.server import create_app

ACCOUNT_A = "alice@example.com"
ACCOUNT_B = "bob@example.com"
PASSWORD = "test-password-123"
TOKEN_A = "a" * 43
TOKEN_B = "b" * 43
REFRESH_URL = "https://prod-01.example.logic.azure.com/trigger?sig=abc"


def graph_message(message_id="<abc@example.com>"):
    return {
        "id": "AAMk-graph-id",
        "internetMessageId": message_id,
        "subject": "DSS5105 Assignment",
        "from": {
            "emailAddress": {
                "name": "Prof Lim",
                "address": "lim@nus.edu.sg",
            }
        },
        "receivedDateTime": "2026-10-28T02:15:00Z",
        "bodyPreview": "Submit by 13 Nov at 23:59",
        "body": {
            "contentType": "html",
            "content": "<p>Submit by <b>13 Nov at 23:59</b></p>",
        },
    }


class InboundWebhookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "multiuser.json"
        path.write_text(
            json.dumps(
                {
                    ACCOUNT_A: {
                        "password_hash": generate_password_hash(PASSWORD),
                        "webhook_token": TOKEN_A,
                        "refresh_url": REFRESH_URL,
                    },
                    ACCOUNT_B: {
                        "password_hash": generate_password_hash(PASSWORD),
                        "webhook_token": TOKEN_B,
                        "refresh_url": "",
                    },
                }
            ),
            encoding="utf-8",
        )
        self.env = patch.dict(os.environ, {"MULTIUSER_CONFIG_FILE": str(path)})
        self.env.start()
        self.addCleanup(self.env.stop)

        pushed_store.clear()
        self.addCleanup(pushed_store.clear)
        self.client = create_app(
            backend="llama", provider="powerautomate"
        ).test_client()

    def push(self, payload=None, token=TOKEN_A, path="/api/inbound/outlook", headers=None):
        request_headers = {"X-Webhook-Token": token}
        if headers:
            request_headers.update(headers)
        return self.client.post(
            path, json=payload or graph_message(), headers=request_headers
        )

    def fetch(self, auth=(ACCOUNT_A, PASSWORD)):
        return self.client.post(
            "/api/emails",
            json={"provider": "powerautomate", "credentials": {}, "count": 10},
            auth=auth,
        )

    def test_valid_token_stores_and_normalises_the_message(self):
        response = self.push()

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "stored")
        self.assertEqual(body["owner"], ACCOUNT_A)

        emails = build_provider("powerautomate", {"owner": ACCOUNT_A}).fetch_emails(
            MailQuery(limit=10)
        )
        self.assertEqual(len(emails), 1)
        email = emails[0]
        self.assertEqual(email.id, "<abc@example.com>")
        self.assertEqual(email.subject, "DSS5105 Assignment")
        self.assertEqual(email.sender, "Prof Lim <lim@nus.edu.sg>")
        self.assertEqual(email.received, "2026-10-28T02:15:00+00:00")
        self.assertEqual(email.body, "Submit by 13 Nov at 23:59")

    def test_wrong_token_is_rejected(self):
        response = self.push(token="wrong")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(pushed_store), 0)

    def test_duplicate_message_id_is_ignored(self):
        self.assertEqual(self.push().status_code, 200)
        response = self.push()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "duplicate")
        self.assertEqual(len(pushed_store), 1)

    def test_pushed_mail_is_scoped_to_its_owner(self):
        self.push(graph_message("<alice@example.com>"), token=TOKEN_A)
        self.push(graph_message("<bob@example.com>"), token=TOKEN_B)

        alice = self.fetch((ACCOUNT_A, PASSWORD)).get_json()["emails"]
        bob = self.fetch((ACCOUNT_B, PASSWORD)).get_json()["emails"]

        self.assertEqual([item["id"] for item in alice], ["<alice@example.com>"])
        self.assertEqual([item["id"] for item in bob], ["<bob@example.com>"])

    def test_api_requires_authentication(self):
        self.assertEqual(self.fetch(auth=None).status_code, 401)

    def test_x_user_email_must_match_the_token(self):
        response = self.push(
            headers={"X-User-Email": ACCOUNT_B},
        )

        self.assertEqual(response.status_code, 403)

    def test_bearer_token_is_accepted(self):
        response = self.client.post(
            "/api/inbound/outlook",
            json=graph_message(),
            headers={"Authorization": f"Bearer {TOKEN_A}"},
        )

        self.assertEqual(response.status_code, 200)

    def test_diagnostics_lists_this_accounts_attempts(self):
        self.push()
        response = self.client.get(
            "/api/inbound/diagnostics", auth=(ACCOUNT_A, PASSWORD)
        )

        self.assertEqual(response.status_code, 200)
        attempts = response.get_json()["attempts"]
        self.assertEqual(attempts[0]["status"], 200)
        self.assertEqual(attempts[0]["owner"], ACCOUNT_A)

    def test_refresh_forwards_owner_and_window(self):
        upstream = MagicMock(status_code=202)
        with patch("app.server.requests.post", return_value=upstream) as post:
            response = self.client.post(
                "/api/inbound/refresh",
                json={
                    "since": "2026-09-28T00:00:00.000Z",
                    "before": "2026-10-28T23:59:59.999Z",
                },
                auth=(ACCOUNT_A, PASSWORD),
            )

        self.assertEqual(response.status_code, 200)
        post.assert_called_once_with(
            REFRESH_URL,
            json={
                "owner": ACCOUNT_A,
                "since": "2026-09-28T00:00:00+00:00",
                "before": "2026-10-28T23:59:59.999000+00:00",
            },
            timeout=15,
            allow_redirects=False,
        )

    def test_refresh_rejects_when_no_url_is_configured(self):
        response = self.client.post(
            "/api/inbound/refresh", json={}, auth=(ACCOUNT_B, PASSWORD)
        )

        self.assertEqual(response.status_code, 503)

    def test_refresh_reports_an_expired_trigger(self):
        with patch(
            "app.server.requests.post", return_value=MagicMock(status_code=401)
        ):
            response = self.client.post(
                "/api/inbound/refresh", json={}, auth=(ACCOUNT_A, PASSWORD)
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("rejected", response.get_json()["error"])

    def test_refresh_reports_an_unreachable_trigger(self):
        with patch(
            "app.server.requests.post",
            side_effect=requests.ConnectionError("boom"),
        ):
            response = self.client.post(
                "/api/inbound/refresh", json={}, auth=(ACCOUNT_A, PASSWORD)
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Could not reach", response.get_json()["error"])


class PushedStoreTests(unittest.TestCase):
    def test_keeps_newest_messages_when_full(self):
        store = PushedStore(2)
        store.add(Email(id="old", received="2026-10-28T01:00:00Z"), ACCOUNT_A)
        store.add(Email(id="new", received="2026-10-28T02:00:00Z"), ACCOUNT_A)
        store.add(Email(id="newest", received="2026-10-28T03:00:00Z"), ACCOUNT_A)

        self.assertEqual([email.id for email in store.all(ACCOUNT_A)], ["newest", "new"])

    def test_same_message_id_for_two_owners_is_stored_twice(self):
        store = PushedStore()
        email = Email(id="shared", received="2026-10-28T02:00:00Z")

        store.add(email, ACCOUNT_A)
        store.add(email, ACCOUNT_B)

        self.assertEqual(len(store.all(ACCOUNT_A)), 1)
        self.assertEqual(len(store.all(ACCOUNT_B)), 1)
