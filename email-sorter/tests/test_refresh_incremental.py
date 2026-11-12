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


def run_sync(state, owner="a@x.com", slices=None, incremental=False, started=T0, requested=SINCE):
    """One refresh run: begin, pushes per slice ``{index: (count, limit)}``, then done."""
    rid, created = state.begin(owner, requested, incremental, now=started)
    assert created
    for index, (count, limit) in (slices or {0: (2, 100)}).items():
        for i in range(count):
            state.arrival(owner, f"<{rid}-{index}-{i}@x>", rid, {"index": index, "limit": limit},
                          now=started + timedelta(seconds=3 + i))
    return rid, state.done(owner, rid, now=started + timedelta(seconds=20))


class RefreshStateTests(unittest.TestCase):
    def test_first_refresh_is_always_full(self):
        self.assertIsNone(RefreshState().incremental_since("a@x.com", SINCE, has_mail=True))

    def test_done_reports_delivery_completeness_and_slices(self):
        _, result = run_sync(RefreshState(), slices={0: (2, 100), 1: (0, 100)})
        report = result["refresh"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual((report["duration_s"], report["first_email_after_s"], report["emails_pushed"]), (20.0, 3.0, 2))
        self.assertTrue(report["delivered"])
        self.assertTrue(report["complete"])
        self.assertEqual([(s["index"], s["count"], s["limit"], s["truncated"]) for s in report["slices"]],
                         [(0, 2, 100, False)])

    def test_after_a_complete_sync_only_newer_mail_is_requested(self):
        state = RefreshState()
        run_sync(state)
        since = state.incremental_since("a@x.com", SINCE + timedelta(days=5), has_mail=True)
        self.assertEqual(since, T0 - timedelta(days=1))  # run start minus the overlap

    def test_a_slice_at_its_limit_is_not_marked_synced(self):
        state = RefreshState()
        _, result = run_sync(state, slices={0: (3, 100), 1: (100, 100)})
        self.assertFalse(result["refresh"]["complete"])
        self.assertTrue(result["refresh"]["delivered"])
        self.assertEqual([s["truncated"] for s in result["refresh"]["slices"]], [False, True])
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=True))  # next one is full

    def test_a_truncated_run_does_not_move_the_checkpoint(self):
        state = RefreshState()
        run_sync(state)                                            # complete: synced through T0
        later = T0 + timedelta(days=3)
        run_sync(state, slices={0: (50, 50)}, incremental=True, started=later)  # cut off
        self.assertEqual(state._data["a@x.com"]["synced_through"], T0.isoformat())
        self.assertEqual(state.incremental_since("a@x.com", SINCE, has_mail=True), T0 - timedelta(days=1))

    def test_mail_dated_outside_its_slice_marks_the_run_incomplete(self):
        """If Outlook ignores a slice's dates, its mail is too new: the range is not trusted."""
        state = RefreshState()
        rid, _ = state.begin("a@x.com", SINCE, False, now=T0)
        info = {"index": 2, "limit": 100, "since": "2026-08-01", "before": "2026-08-31"}
        state.arrival("a@x.com", "<in@x>", rid, info, now=T0, received=datetime(2026, 8, 15, tzinfo=timezone.utc))
        state.arrival("a@x.com", "<edge@x>", rid, info, now=T0, received=datetime(2026, 9, 1, tzinfo=timezone.utc))
        state.arrival("a@x.com", "<new@x>", rid, info, now=T0, received=datetime(2026, 10, 30, tzinfo=timezone.utc))
        report = state.done("a@x.com", rid, now=T0)["refresh"]
        self.assertEqual(report["slices"][0]["outside"], 1)  # one day of slack for time zones
        self.assertFalse(report["complete"])
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=True))

    def test_retried_pushes_are_counted_once(self):
        state = RefreshState()
        rid, _ = state.begin("a@x.com", SINCE, False, now=T0)
        for _ in range(3):  # Power Automate retried the same email
            state.arrival("a@x.com", "<same@x>", rid, {"index": 0, "limit": 2}, now=T0)
        self.assertTrue(state.done("a@x.com", rid, now=T0)["refresh"]["complete"])

    def test_unfinished_refresh_does_not_count_as_synced(self):
        state = RefreshState()
        state.begin("a@x.com", SINCE, False, now=T0)  # the flow never called "done"
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=True))

    def test_a_second_refresh_joins_the_running_one(self):
        state = RefreshState()
        first, created = state.begin("a@x.com", SINCE, False, now=T0)
        again, created_again = state.begin("a@x.com", SINCE, False, now=T0 + timedelta(minutes=1))
        self.assertTrue(created)
        self.assertEqual((again, created_again), (first, False))

    def test_a_lost_callback_times_out_and_its_late_done_is_stale(self):
        state = RefreshState()
        old, _ = state.begin("a@x.com", SINCE, False, now=T0)
        later = T0 + RefreshState.PENDING_TIMEOUT + timedelta(minutes=1)
        new, created = state.begin("a@x.com", SINCE, False, now=later)
        self.assertTrue(created)
        self.assertNotEqual(old, new)
        self.assertEqual(state.status("a@x.com", now=later)["running"]["refresh_id"], new)
        # The old run's pushes and "done" arrive late: ignored, nothing marked synced.
        state.arrival("a@x.com", "<late@x>", old, {"index": 0, "limit": 1}, now=later)
        self.assertEqual(state.done("a@x.com", old, now=later)["status"], "stale")
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=True))
        self.assertEqual(state.status("a@x.com", now=later)["running"]["emails_pushed"], 0)

    def test_status_reports_a_timed_out_run(self):
        state = RefreshState()
        state.begin("a@x.com", SINCE, False, now=T0)
        status = state.status("a@x.com", now=T0 + timedelta(hours=1))
        self.assertIsNone(status["running"])
        self.assertEqual(status["last"]["status"], "timed_out")

    def test_failed_invocation_closes_the_run_without_coverage(self):
        state = RefreshState()
        rid, _ = state.begin("a@x.com", SINCE, False, now=T0)
        state.failed("a@x.com", rid, "flow unreachable", now=T0)
        self.assertIsNone(state.status("a@x.com", now=T0)["running"])
        self.assertEqual(state.last("a@x.com")["status"], "failed")
        self.assertEqual(state.done("a@x.com", rid, now=T0)["status"], "no_refresh")
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=True))

    def test_an_old_flow_without_ids_is_never_marked_complete(self):
        state = RefreshState()
        state.begin("a@x.com", SINCE, False, now=T0)
        state.arrival("a@x.com", "<1@x>", None, None, now=T0)
        result = state.done("a@x.com", None, now=T0)
        self.assertEqual(result["status"], "unverified")
        self.assertIsNone(result["refresh"]["complete"])
        self.assertEqual(result["refresh"]["emails_pushed"], 1)
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=True))

    def test_bigger_window_or_lost_mail_forces_a_full_read(self):
        state = RefreshState()
        run_sync(state)
        self.assertIsNone(state.incremental_since("a@x.com", SINCE - timedelta(days=30), has_mail=True))
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=False))

    def test_requested_window_not_the_query_overlap_is_recorded(self):
        state = RefreshState()
        run_sync(state)
        later = T0 + timedelta(days=2)
        # An incremental run queries from T0 - 1 day, but the covered start stays SINCE.
        run_sync(state, incremental=True, started=later)
        self.assertEqual(state._data["a@x.com"]["synced_since"], SINCE.isoformat(timespec="seconds"))
        self.assertEqual(state._data["a@x.com"]["synced_through"], later.isoformat(timespec="seconds"))
        self.assertEqual(state.incremental_since("a@x.com", SINCE, has_mail=True), later - timedelta(days=1))

    def test_checkpoints_from_before_completeness_checks_are_ignored(self):
        state = RefreshState()
        state._data["a@x.com"] = {"synced_since": SINCE.isoformat(), "synced_through": T0.isoformat()}
        self.assertIsNone(state.incremental_since("a@x.com", SINCE, has_mail=True))  # one full read first

    def test_state_is_saved_but_runs_in_progress_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = RefreshState(path)
            run_sync(state)
            rid, _ = state.begin("a@x.com", SINCE, False, now=T0 + timedelta(days=1))
            again = RefreshState(path)  # a restart
            self.assertIsNotNone(again.incremental_since("a@x.com", SINCE + timedelta(days=5), has_mail=True))
            self.assertEqual(again.done("a@x.com", rid)["status"], "no_refresh")


class FlushOrderTests(unittest.TestCase):
    def test_an_older_snapshot_never_overwrites_a_newer_one(self):
        """Flush A snapshots and is slow to write; flush B (newer) must not finish first."""
        import threading

        from app.stores import jsonfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pushed.json"
            store = PushedStore(10, path)
            store.add(Email(id="<old@x>"), "a@x.com")
            first_write_started, release_first = threading.Event(), threading.Event()
            real_write = jsonfile.write_json_atomic

            def slow_first_write(target, rows):
                if not first_write_started.is_set():
                    first_write_started.set()
                    release_first.wait(5)
                real_write(target, rows)

            with patch("app.mail.pushed_store.write_json_atomic", side_effect=slow_first_write):
                a = threading.Thread(target=store.flush)
                a.start()
                first_write_started.wait(5)
                store.add(Email(id="<new@x>"), "a@x.com")
                b = threading.Thread(target=store.flush)
                b.start()
                b.join(0.3)  # B must wait for A instead of writing first
                release_first.set()
                a.join(5)
                b.join(5)
            saved = {row["email"]["id"] for row in json.loads(path.read_text())}
            self.assertEqual(saved, {"<old@x>", "<new@x>"})


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

    def refresh(self, body=None, status=202):
        with patch("app.routes.inbound.requests.post", return_value=MagicMock(status_code=status)) as post:
            response = self.client.post("/api/inbound/refresh", json=body or {}, auth=(ACCOUNT_A, PASSWORD))
        return response, post

    def push(self, refresh_id, message_id="<abc@example.com>", slice_index="0", slice_top="100"):
        body = {**graph_message(message_id), "refreshId": refresh_id, "slice": slice_index,
                "sliceTop": slice_top, "sliceSince": "2026-08-01", "sliceBefore": ""}
        return self.client.post("/api/inbound/outlook", json=body, headers={"X-Webhook-Token": TOKEN_A})

    def done(self, refresh_id="", token=TOKEN_A):
        return self.client.post("/api/inbound/refresh-done", json={"refreshId": refresh_id},
                                headers={"X-Webhook-Token": token})

    def full_cycle(self, body=None):
        rid = self.refresh(body)[0].get_json()["refresh_id"]
        self.push(rid)
        return rid, self.done(rid).get_json()

    def test_full_cycle_then_incremental(self):
        since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        with patch("app.routes.inbound.settings", replace(settings, flow_refresh_top=0)):
            first, post = self.refresh({"since": since})
            self.assertFalse(first.get_json()["incremental"])
            rid = first.get_json()["refresh_id"]
            self.assertEqual(post.call_args.kwargs["json"]["refreshId"], rid)
            self.push(rid)
            self.assertEqual(self.done(rid).get_json()["status"], "ok")

            second, post = self.refresh({"since": since})
        self.assertTrue(second.get_json()["incremental"])
        sent = datetime.fromisoformat(post.call_args.kwargs["json"]["since"])
        self.assertGreater(sent, datetime.fromisoformat(since) + timedelta(days=80))

    def test_a_slice_at_its_limit_keeps_the_next_refresh_full(self):
        rid = self.refresh({})[0].get_json()["refresh_id"]
        for i in range(2):
            self.push(rid, f"<{i}@x>", slice_index="1", slice_top="2")
        report = self.done(rid).get_json()["refresh"]
        self.assertFalse(report["complete"])
        self.assertEqual(report["slices"][0]["count"], 2)
        self.assertFalse(self.refresh({})[0].get_json()["incremental"])
        diag = self.client.get("/api/inbound/diagnostics", auth=(ACCOUNT_A, PASSWORD)).get_json()
        self.assertFalse(diag["last_refresh"]["complete"])

    def test_a_second_refresh_while_running_does_not_call_the_flow_again(self):
        rid = self.refresh({})[0].get_json()["refresh_id"]
        response, post = self.refresh({})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["already_running"])
        self.assertEqual(response.get_json()["refresh_id"], rid)
        post.assert_not_called()

    def test_failed_flow_call_closes_the_run(self):
        response, _ = self.refresh({}, status=500)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.done("anything").get_json()["status"], "no_refresh")
        self.assertTrue(self.refresh({})[0].get_json()["requested"])  # a new run may start

    def test_a_done_for_another_run_is_stale(self):
        self.refresh({})
        result = self.done("not-this-run").get_json()
        self.assertEqual(result["status"], "stale")
        self.assertIsNone(result["refresh"])

    def test_an_old_flow_without_ids_is_unverified(self):
        self.refresh({})
        self.client.post("/api/inbound/outlook", json=graph_message(), headers={"X-Webhook-Token": TOKEN_A})
        result = self.done("").get_json()
        self.assertEqual(result["status"], "unverified")
        self.assertFalse(self.refresh({})[0].get_json()["incremental"])

    def test_emails_report_sync_progress(self):
        rid = self.refresh({})[0].get_json()["refresh_id"]
        self.push(rid)

        def sync():
            return self.client.post("/api/emails", json={"provider": "powerautomate", "count": 10},
                                    auth=(ACCOUNT_A, PASSWORD)).get_json()["sync"]

        running = sync()["running"]
        self.assertEqual((running["refresh_id"], running["emails_pushed"]), (rid, 1))
        self.done(rid)
        after = sync()
        self.assertIsNone(after["running"])
        self.assertTrue(after["last"]["complete"])

    def test_full_flag_and_custom_band_skip_incremental(self):
        since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        self.full_cycle({"since": since})
        rid, _ = self.full_cycle({"since": since, "full": True})
        self.assertFalse(self.refresh({"since": since, "before": datetime.now(timezone.utc).isoformat()})[0]
                         .get_json()["incremental"])

    def test_incremental_can_be_switched_off(self):
        since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        self.full_cycle({"since": since})
        with patch("app.routes.inbound.settings", replace(settings, flow_incremental=False)):
            self.assertFalse(self.refresh({"since": since})[0].get_json()["incremental"])

    def test_done_needs_the_webhook_token(self):
        self.assertEqual(self.done(token="wrong").status_code, 401)

    def test_diagnostics_show_the_last_refresh(self):
        self.full_cycle()
        data = self.client.get("/api/inbound/diagnostics", auth=(ACCOUNT_A, PASSWORD)).get_json()
        self.assertEqual(data["last_refresh"]["emails_pushed"], 1)
        self.assertIn("duration_s", data["last_refresh"])
        self.assertIsNone(data["refresh"]["running"])


class FlowDoneStepTests(unittest.TestCase):
    def definition(self, batches):
        from app.mail.flow_package import _definition

        with patch("app.mail.flow_package.BATCHES", batches):
            return _definition("https://x/api/inbound/outlook", "a@u.nus.edu", "t" * 43)["properties"]["definition"]

    def test_flow_ends_by_telling_the_app_which_run_finished(self):
        for batches in (1, 3):
            actions = self.definition(batches)["actions"]
            done = actions["Refresh_done"]
            last = "Each_batch" if batches > 1 else "Send_each_email"
            self.assertEqual(done["runAfter"], {last: ["Succeeded"]})
            self.assertEqual(done["inputs"]["uri"], "https://x/api/inbound/refresh-done")
            self.assertEqual(done["inputs"]["headers"]["X-Webhook-Token"], "t" * 43)
            self.assertEqual(done["inputs"]["body"], {"refreshId": "@{triggerBody()?['refreshId']}"})

    def test_every_push_names_its_run_slice_and_limit(self):
        for batches, loop in ((1, None), (3, "Each_batch")):
            actions = self.definition(batches)["actions"]
            inner = actions[loop]["actions"] if loop else actions
            body = inner["Send_each_email"]["actions"]["HTTP"]["inputs"]["body"]
            self.assertEqual(body["refreshId"], "@{triggerBody()?['refreshId']}")
            for key in ("slice", "sliceTop", "sliceSince", "sliceBefore"):
                self.assertIn(key, body)
            self.assertIn("refreshId", self.definition(batches)["triggers"]["manual"]["inputs"]["schema"]["properties"])

    def test_outer_date_bounds_are_widened_not_cut(self):
        query = self.definition(3)["actions"]["Each_batch"]["actions"]["Get_emails_(V3)"]["inputs"]["parameters"]["searchQuery"]
        self.assertIn("addDays(outputs('Window_start'), -1)", query)  # oldest slice starts a day early
        self.assertIn("equals(triggerBody()?['before'], null)", query)  # newest: no upper bound ...
        self.assertIn("concat('received>=', ", query)                 # ... so just "received>=START"
        self.assertIn("addDays(outputs('Window_end'), 2)", query)     # ... or two days past "before"
        flat = self.definition(1)["actions"]["Get_emails_(V3)"]["inputs"]["parameters"]["searchQuery"]
        self.assertIn(", -1), 'yyyy-MM-dd')", flat)


if __name__ == "__main__":
    unittest.main()
