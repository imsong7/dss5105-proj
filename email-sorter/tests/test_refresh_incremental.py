"""Saved pushed mail, incremental refreshes and the flow's "done" signal."""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from werkzeug.security import generate_password_hash

from app.config import settings
from app.mail.pushed_store import PushedStore, RefreshState, pushed_store
from app.schemas import Email
from app.server import create_app
from tests.test_inbound_webhook import ACCOUNT_A, PASSWORD, REFRESH_URL, TOKEN_A, graph_message

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
SINCE = T0 - timedelta(days=90)


class SavedMailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "pushed.json"

    def test_mail_survives_a_restart_with_its_ocr_flag(self):
        store = PushedStore(10, self.path)
        email = Email(id="<1@x>", subject="Hi", received="2026-10-28T02:15:00+00:00", poster={"venue": "MPSH"})
        email._ocr_checked = True
        store.add(email, "A@x.com")
        store.flush()

        again = PushedStore(10, self.path)
        [loaded] = again.all("a@x.com")
        self.assertEqual((loaded.subject, loaded.poster), ("Hi", {"venue": "MPSH"}))
        self.assertTrue(loaded._ocr_checked)

    def test_a_burst_of_pushes_is_saved_once(self):
        store = PushedStore(500, self.path)
        with patch("app.mail.pushed_store.write_json_atomic") as write:
            for i in range(50):
                store.add(Email(id=f"<{i}@x>"), "a@x.com")
            self.assertEqual(write.call_count, 0)  # nothing written per email
            store.flush()
            self.assertEqual(write.call_count, 1)

    def test_broken_file_or_row_is_skipped(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(len(PushedStore(10, self.path)), 0)
        self.path.write_text(json.dumps([{"owner": "a", "email": {"nope": 1}},
                                         {"owner": "a", "email": {"id": "ok"}}]), encoding="utf-8")
        self.assertEqual([e.id for e in PushedStore(10, self.path).all("a")], ["ok"])

    def test_save_failure_never_breaks_a_push(self):
        store = PushedStore(10, self.path)
        store.add(Email(id="<1@x>"), "a@x.com")
        with patch("app.mail.pushed_store.write_json_atomic", side_effect=OSError("disk full")):
            store.flush()  # must not raise
        self.assertEqual(len(store), 1)

    def test_no_path_means_no_saving(self):
        store = PushedStore(10)
        store.add(Email(id="<1@x>"), "a@x.com")
        store.flush()
        self.assertEqual(len(store), 1)


class RefreshStateTests(unittest.TestCase):
    def full_sync(self, state, owner="a@x.com"):
        state.started(owner, SINCE, incremental=False, now=T0)
        state.arrival(owner, T0 + timedelta(seconds=3))
        state.arrival(owner, T0 + timedelta(seconds=4))
        return state.done(owner, T0 + timedelta(seconds=20))

    def test_first_refresh_is_always_full(self):
        self.assertIsNone(RefreshState().incremental_since("a@x.com", SINCE, has_mail=True))

    def test_done_reports_timings(self):
        last = self.full_sync(RefreshState())
        self.assertEqual((last["duration_s"], last["first_email_after_s"], last["emails_pushed"]), (20.0, 3.0, 2))
        self.assertFalse(last["incremental"])

    def test_after_a_complete_sync_only_newer_mail_is_requested(self):
        state = RefreshState()
        self.full_sync(state)
        since = state.incremental_since("a@x.com", SINCE + timedelta(days=5), has_mail=True)
        self.assertEqual(since, T0 - timedelta(days=1))  # sync start minus the overlap

    def test_unfinished_refresh_does_not_count_as_synced(self):
        state = RefreshState()
        state.started("a@x.com", SINCE, incremental=False, now=T0)  # the flow never called "done"
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=True))

    def test_bigger_window_or_lost_mail_forces_a_full_read(self):
        state = RefreshState()
        self.full_sync(state)
        self.assertIsNone(state.incremental_since("a@x.com", SINCE - timedelta(days=30), has_mail=True))
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=False))

    def test_incremental_run_keeps_the_covered_start(self):
        state = RefreshState()
        self.full_sync(state)
        later = T0 + timedelta(days=2)
        state.started("a@x.com", SINCE, incremental=True, now=later)
        state.done("a@x.com", later + timedelta(seconds=2))
        self.assertEqual(state._data["a@x.com"]["synced_since"], SINCE.isoformat(timespec="seconds"))
        self.assertEqual(
            state.incremental_since("a@x.com", SINCE, has_mail=True), later - timedelta(days=1)
        )

    def test_state_is_saved_and_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            self.full_sync(RefreshState(path))
            again = RefreshState(path)
            self.assertIsNotNone(again.incremental_since("a@x.com", SINCE + timedelta(days=5), has_mail=True))


class RefreshEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "multiuser.json"
        path.write_text(json.dumps({ACCOUNT_A: {
            "password_hash": generate_password_hash(PASSWORD),
            "webhook_token": TOKEN_A, "refresh_url": REFRESH_URL}}), encoding="utf-8")
        env = patch.dict(os.environ, {"MULTIUSER_CONFIG_FILE": str(path)})
        env.start()
        self.addCleanup(env.stop)
        pushed_store.clear()
        self.addCleanup(pushed_store.clear)
        self.client = create_app(backend="llama", provider="powerautomate").test_client()

    def refresh(self, body=None):
        with patch("app.routes.inbound.requests.post", return_value=MagicMock(status_code=202)) as post:
            response = self.client.post("/api/inbound/refresh", json=body or {}, auth=(ACCOUNT_A, PASSWORD))
        return response, post

    def push_one(self):
        return self.client.post("/api/inbound/outlook", json=graph_message(), headers={"X-Webhook-Token": TOKEN_A})

    def done(self, token=TOKEN_A):
        return self.client.post("/api/inbound/refresh-done", json={}, headers={"X-Webhook-Token": token})

    def test_full_cycle_then_incremental(self):
        since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        with patch("app.routes.inbound.settings", replace(settings, flow_refresh_top=0)):
            first, _ = self.refresh({"since": since})
            self.assertFalse(first.get_json()["incremental"])
            self.push_one()
            self.assertEqual(self.done().status_code, 200)

            second, post = self.refresh({"since": since})
        self.assertTrue(second.get_json()["incremental"])
        sent = datetime.fromisoformat(post.call_args.kwargs["json"]["since"])
        self.assertGreater(sent, datetime.fromisoformat(since) + timedelta(days=80))

    def test_full_flag_and_custom_band_skip_incremental(self):
        since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        self.refresh({"since": since})
        self.push_one()
        self.done()
        self.assertFalse(self.refresh({"since": since, "full": True})[0].get_json()["incremental"])
        before = datetime.now(timezone.utc).isoformat()
        self.assertFalse(self.refresh({"since": since, "before": before})[0].get_json()["incremental"])

    def test_incremental_can_be_switched_off(self):
        since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        self.refresh({"since": since})
        self.push_one()
        self.done()
        with patch("app.routes.inbound.settings", replace(settings, flow_incremental=False)):
            self.assertFalse(self.refresh({"since": since})[0].get_json()["incremental"])

    def test_done_needs_the_webhook_token(self):
        self.assertEqual(self.done(token="wrong").status_code, 401)

    def test_diagnostics_show_the_last_refresh(self):
        self.refresh({})
        self.push_one()
        self.done()
        data = self.client.get("/api/inbound/diagnostics", auth=(ACCOUNT_A, PASSWORD)).get_json()
        self.assertEqual(data["last_refresh"]["emails_pushed"], 1)
        self.assertIn("duration_s", data["last_refresh"])

    def test_failed_flow_call_does_not_start_a_refresh(self):
        with patch("app.routes.inbound.requests.post", return_value=MagicMock(status_code=500)):
            self.client.post("/api/inbound/refresh", json={}, auth=(ACCOUNT_A, PASSWORD))
        self.assertIsNone(self.done().get_json()["refresh"])


class FlowDoneStepTests(unittest.TestCase):
    def test_flow_ends_by_telling_the_app_it_finished(self):
        from app.mail.flow_package import _definition

        for batches in (1, 3):
            with patch("app.mail.flow_package.BATCHES", batches):
                actions = _definition("https://x/api/inbound/outlook", "a@u.nus.edu", "t" * 43)[
                    "properties"]["definition"]["actions"]
            done = actions["Refresh_done"]
            last = "Each_batch" if batches > 1 else "Send_each_email"
            self.assertEqual(done["runAfter"], {last: ["Succeeded"]})
            self.assertEqual(done["inputs"]["uri"], "https://x/api/inbound/refresh-done")
            self.assertEqual(done["inputs"]["headers"]["X-Webhook-Token"], "t" * 43)


if __name__ == "__main__":
    unittest.main()
