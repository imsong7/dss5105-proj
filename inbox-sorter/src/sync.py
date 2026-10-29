"""One sync: read new Inbox mail with the pasted token, classify with Claude, store the labels.

Used by both the dashboard's "Sync now" button and the background worker.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import store
from .graph import list_inbox, my_address
from .llm import ClaudeClassifier
from .pipeline import classify
from .preprocess import to_record

log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    fetched: int = 0
    labelled: int = 0
    remaining: int = 0          # left for the next sync because of max_per_sync
    failed: int = 0             # sent to Further review because Claude failed
    last_error: str | None = None


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_once(con, cfg: dict, token: str, classifier: ClaudeClassifier | None = None) -> SyncReport:
    classifier = classifier or ClaudeClassifier(cfg)
    w = cfg["worker"]

    me = store.get_state(con, "my_address")
    if not me:
        me = my_address(token)
        store.set_state(con, "my_address", me)

    latest = store.latest_received(con)
    if latest:  # overlap by an hour to catch late-arriving mail; duplicates are skipped
        since = datetime.fromisoformat(latest.replace("Z", "+00:00")) - timedelta(hours=1)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=w.get("backfill_days", 7))

    msgs = list_inbox(token, _iso_z(since), max_n=5000)
    todo = sorted((m for m in msgs if not store.already_labelled(con, m["id"])),
                  key=lambda m: m.get("receivedDateTime", ""))       # oldest first
    cap = w.get("max_per_sync", 200)
    rep = SyncReport(fetched=len(msgs), remaining=max(0, len(todo) - cap))
    visible = not w.get("shadow_mode", False)

    for m in todo[:cap]:
        rec = to_record(m, me, cfg)
        r = classify(rec, cfg, classifier)
        if r.source == "fallback" and classifier.api_failed:
            # Don't file it as Further review: leave it unlabelled so the next sync retries it.
            rep.last_error = classifier.last_error
            rep.remaining = len(todo) - rep.labelled
            log.error("Claude API unavailable (%s); stopping this sync", classifier.last_error)
            break
        store.save(con, rec, r, classifier.model, visible)
        rep.labelled += 1
        if r.source == "fallback":
            rep.failed += 1
            rep.last_error = classifier.last_error
        log.info("labelled %s -> %s / %s (%s)", m["id"][-12:], r.topic, r.action, r.source)

    store.set_state(con, "last_sync", store.now())
    return rep
