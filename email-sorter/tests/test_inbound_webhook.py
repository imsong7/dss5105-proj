import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

import requests

from app.config import settings
from app.inbound_store import InboundStore, inbound_store
from app.models import Email
from app.providers import build_provider
from app.providers.base import MailQuery
from app.server import create_app

TOKEN = "test-webhook-token"


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
        inbound_store.clear()
        self.addCleanup(inbound_store.clear)
        self.client = create_app(backend="llama").test_client()

    def post(self, payload, token=TOKEN, header="X-Webhook-Token", path="/api/inbound/outlook"):
        return self.client.post(
            path,
            json=payload,
            headers={header: token},
        )

    def test_rejects_when_no_token_is_configured(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token="")):
            response = self.post(graph_message())

        self.assertEqual(response.status_code, 503)
        self.assertIn("POWER_AUTOMATE_WEBHOOK_TOKEN", response.get_json()["error"])

    def test_rejects_wrong_token(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            response = self.post(graph_message(), token="wrong")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(inbound_store), 0)

    def test_stores_graph_message_and_normalises_fields(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            response = self.post(graph_message())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "stored")
        self.assertEqual(response.get_json()["stored"], 1)

        emails = build_provider("powerautomate", {}).fetch_emails(MailQuery(limit=10))
        self.assertEqual(len(emails), 1)
        email = emails[0]
        self.assertEqual(email.id, "<abc@example.com>")
        self.assertEqual(email.subject, "DSS5105 Assignment")
        self.assertEqual(email.sender, "Prof Lim <lim@nus.edu.sg>")
        self.assertEqual(email.received, "2026-10-28T02:15:00+00:00")
        self.assertEqual(email.body, "Submit by 13 Nov at 23:59")
        self.assertEqual(email.preview, "Submit by 13 Nov at 23:59")

    def test_stores_a_flat_body_without_nested_objects(self):
        payload = {
            "id": "flat-1",
            "subject": "Submission deadline extended",
            "fromName": "Prof Lim",
            "fromAddress": "lim@nus.edu.sg",
            "receivedDateTime": "2026-10-28T03:21:35Z",
            "bodyPreview": "The deadline is now 13 Nov 23:59.",
            "bodyText": "<p>The deadline is now <b>13 Nov 23:59</b>.</p>",
            "owner": "flat.user@u.nus.edu",
        }
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            response = self.post(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["owner"], "flat.user@u.nus.edu")
        email = build_provider("powerautomate", {"owner": "flat.user@u.nus.edu"}).fetch_emails(
            MailQuery(limit=10)
        )[0]
        self.assertEqual(email.sender, "Prof Lim <lim@nus.edu.sg>")
        self.assertEqual(email.body, "The deadline is now 13 Nov 23:59.")
        self.assertEqual(email.preview, "The deadline is now 13 Nov 23:59.")

    def test_duplicate_message_id_is_ignored(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            self.assertEqual(self.post(graph_message()).status_code, 200)
            response = self.post(graph_message())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "duplicate")
        self.assertEqual(len(inbound_store), 1)

    def test_accepts_dotnet_fractional_seconds(self):
        payload = graph_message("<fraction@example.com>")
        payload["receivedDateTime"] = "2026-10-28T02:15:00.1234567Z"
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            self.assertEqual(self.post(payload).status_code, 200)

        email = build_provider("powerautomate", {}).fetch_emails(MailQuery(limit=10))[0]
        self.assertEqual(email.received, "2026-10-28T02:15:00.123456+00:00")

    def test_accepts_bearer_token(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            response = self.post(
                graph_message(), header="Authorization", token=f"Bearer {TOKEN}"
            )

        self.assertEqual(response.status_code, 200)

    def test_get_on_the_webhook_explains_the_post_requirement(self):
        page = self.client.get("/api/inbound/outlook", headers={"Accept": "text/html"})
        self.assertEqual(page.status_code, 405)
        self.assertIn(b"only accepts POST", page.data)
        self.assertIn(b"Method to POST", page.data)

        as_json = self.client.get(
            "/api/inbound/outlook", headers={"Accept": "application/json"}
        )
        self.assertEqual(as_json.status_code, 405)
        self.assertIn("POST", as_json.get_json()["error"])

    def test_diagnostics_records_the_last_successful_push(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            self.post(graph_message())
            data = self.client.get("/api/inbound/diagnostics").get_json()

        self.assertTrue(data["configured"])
        self.assertEqual(data["endpoint"], "/api/inbound/outlook")
        last = data["attempts"][0]
        self.assertEqual(last["method"], "POST")
        self.assertEqual(last["path"], "/api/inbound/outlook")
        self.assertEqual(last["status"], 200)
        self.assertEqual(last["result"], "stored")

    def test_diagnostics_records_a_wrong_path(self):
        self.client.post("/", headers={"Accept": "text/html"})

        last = self.client.get("/api/inbound/diagnostics").get_json()["attempts"][0]

        self.assertEqual(last["path"], "/")
        self.assertEqual(last["status"], 405)

    def test_diagnostics_records_a_successful_post_to_the_root(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            self.post(graph_message(), path="/")

        last = self.client.get("/api/inbound/diagnostics").get_json()["attempts"][0]

        self.assertEqual(last["path"], "/")
        self.assertEqual(last["status"], 200)
        self.assertEqual(last["result"], "stored")

    def test_a_flow_posting_to_the_root_still_delivers_its_mail(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            response = self.post(graph_message(), path="/")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "stored")
        self.assertIn("/api/inbound/outlook", body["warning"])

    def test_post_to_the_dashboard_root_points_at_the_webhook(self):
        page = self.client.post("/", headers={"Accept": "text/html"})

        self.assertEqual(page.status_code, 405)
        self.assertIn(b"/api/inbound/outlook", page.data)

    def test_fetches_pushed_mail_through_the_existing_email_api(self):
        with patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN)):
            self.post(graph_message())

        response = self.client.post(
            "/api/emails",
            json={"provider": "powerautomate", "credentials": {}, "count": 10},
        )

        self.assertEqual(response.status_code, 200)
        emails = response.get_json()["emails"]
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0]["deadline_candidate"]["date"], "2026-11-13")


class MultiUserInboundTests(unittest.TestCase):
    def setUp(self):
        inbound_store.clear()
        self.addCleanup(inbound_store.clear)
        self.client = create_app(backend="llama").test_client()
        self.settings = patch("app.server.settings", replace(settings, inbound_webhook_token=TOKEN))
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def post_as(self, payload, user):
        headers = {"X-Webhook-Token": TOKEN}
        if user:
            headers["X-User-Email"] = user
        return self.client.post("/api/inbound/outlook", json=payload, headers=headers)

    def fetch_as(self, user):
        headers = {"X-User-Email": user} if user else {}
        return self.client.post(
            "/api/emails",
            json={"provider": "powerautomate", "credentials": {}, "count": 10},
            headers=headers,
        )

    def test_pushed_mail_is_scoped_to_its_owner(self):
        self.post_as(graph_message("<alice@example.com>"), "Alice@U.NUS.edu")
        self.post_as(graph_message("<bob@example.com>"), "bob@u.nus.edu")

        alice = self.fetch_as("alice@u.nus.edu").get_json()["emails"]
        bob = self.fetch_as("bob@u.nus.edu").get_json()["emails"]
        carol = self.fetch_as("carol@u.nus.edu").get_json()["emails"]

        self.assertEqual([email["id"] for email in alice], ["<alice@example.com>"])
        self.assertEqual([email["id"] for email in bob], ["<bob@example.com>"])
        self.assertEqual(carol, [])

    def test_webhook_reports_the_owner_it_stored(self):
        response = self.post_as(graph_message(), "Alice@U.NUS.edu")

        self.assertEqual(response.get_json()["owner"], "alice@u.nus.edu")

    def test_owner_falls_back_to_the_to_recipient(self):
        payload = graph_message("<to-header@example.com>")
        payload["toRecipients"] = [{"emailAddress": {"address": "Carol@U.NUS.edu"}}]

        response = self.post_as(payload, "")

        self.assertEqual(response.get_json()["owner"], "carol@u.nus.edu")
        carol = self.fetch_as("carol@u.nus.edu").get_json()["emails"]
        self.assertEqual([email["id"] for email in carol], ["<to-header@example.com>"])

    def test_same_message_id_for_two_owners_is_stored_twice(self):
        self.post_as(graph_message("<shared@example.com>"), "alice@u.nus.edu")
        second = self.post_as(graph_message("<shared@example.com>"), "bob@u.nus.edu")

        self.assertEqual(second.get_json()["status"], "stored")
        self.assertEqual(second.get_json()["stored"], 2)

    def test_retry_from_the_same_owner_is_a_duplicate(self):
        self.post_as(graph_message("<shared@example.com>"), "alice@u.nus.edu")
        second = self.post_as(graph_message("<shared@example.com>"), "alice@u.nus.edu")

        self.assertEqual(second.get_json()["status"], "duplicate")
        self.assertEqual(second.get_json()["stored"], 1)

    def test_unowned_mail_stays_hidden_from_identified_users(self):
        self.post_as(graph_message("<orphan@example.com>"), "")

        self.assertEqual(self.fetch_as("alice@u.nus.edu").get_json()["emails"], [])
        # A request without an identity still sees the unassigned bucket, so a
        # single-user setup keeps working when no header is configured.
        self.assertEqual(len(self.fetch_as("").get_json()["emails"]), 1)


class InboundRefreshTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(backend="llama").test_client()
        self.url = "https://prod-01.example.logic.azure.com/trigger?sig=abc"

    def post(self, payload, user="alice@u.nus.edu"):
        headers = {"X-User-Email": user} if user else {}
        return self.client.post("/api/inbound/refresh", json=payload, headers=headers)

    def test_rejects_when_no_trigger_url_is_configured(self):
        with patch("app.server.settings", replace(settings, powerautomate_refresh_url="")):
            response = self.post({})

        self.assertEqual(response.status_code, 503)
        self.assertIn("POWER_AUTOMATE_REFRESH_URL", response.get_json()["error"])

    def test_forwards_owner_and_window_to_the_flow(self):
        upstream = MagicMock(status_code=202)
        with patch("app.server.settings", replace(settings, powerautomate_refresh_url=self.url)), \
                patch("app.server.requests.post", return_value=upstream) as post:
            response = self.post({
                "since": "2026-09-28T00:00:00.000Z",
                "before": "2026-10-28T23:59:59.999Z",
            })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["requested"])
        post.assert_called_once_with(
            self.url,
            json={
                "owner": "alice@u.nus.edu",
                "since": "2026-09-28T00:00:00.000Z",
                "before": "2026-10-28T23:59:59.999Z",
            },
            timeout=15,
        )

    def test_reports_an_expired_trigger_url(self):
        upstream = MagicMock(status_code=401)
        with patch("app.server.settings", replace(settings, powerautomate_refresh_url=self.url)), \
                patch("app.server.requests.post", return_value=upstream):
            response = self.post({})

        self.assertEqual(response.status_code, 502)
        self.assertIn("expired", response.get_json()["error"])

    def test_reports_an_unreachable_trigger(self):
        with patch("app.server.settings", replace(settings, powerautomate_refresh_url=self.url)), \
                patch("app.server.requests.post", side_effect=requests.ConnectionError("boom")):
            response = self.post({})

        self.assertEqual(response.status_code, 502)
        self.assertIn("Could not reach", response.get_json()["error"])


class InboundStoreTests(unittest.TestCase):
    def test_keeps_newest_messages_when_full(self):
        store = InboundStore(2)
        store.add(Email(id="new", received="2026-10-28T02:00:00Z"), "a@u.nus.edu")
        store.add(Email(id="old", received="2026-10-01T02:00:00Z"), "b@u.nus.edu")
        store.add(Email(id="middle", received="2026-10-20T02:00:00Z"), "a@u.nus.edu")

        self.assertEqual({email.id for email in store.all("a@u.nus.edu")}, {"new", "middle"})

    def test_same_message_id_is_stored_once_per_owner(self):
        store = InboundStore(10)
        store.add(Email(id="same"), "a@u.nus.edu")
        _, duplicate = store.add(Email(id="same"), "a@u.nus.edu")
        _, other_owner = store.add(Email(id="same"), "b@u.nus.edu")

        self.assertTrue(duplicate)
        self.assertFalse(other_owner)
        self.assertEqual(len(store.all("a@u.nus.edu")), 1)
        self.assertEqual(len(store.all("b@u.nus.edu")), 1)
        self.assertEqual(store.owners(), ["b@u.nus.edu", "a@u.nus.edu"])


if __name__ == "__main__":
    unittest.main()
