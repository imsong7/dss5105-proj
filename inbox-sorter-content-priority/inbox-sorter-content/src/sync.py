"""One sync: read new Inbox mail with the pasted token, classify with Claude, store the labels.

Used by both the dashboard's "Sync now" button and the background worker.

  python -m src.sync                          # one sync from the command line
  python -m src.sync --reclassify --days 14   # fill in emails that have no stars, and redo emails whose
                                              # classification failed (one API call per email)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import store
from .graph import list_inbox, my_address
from .llm import ClaudeClassifier
from .pipeline import Result, classify
from .priority import compute
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


def reclassify_priority(con, cfg: dict, token: str, days: int, classifier: ClaudeClassifier | None = None,
                        include_rated: bool = False) -> tuple[int, str | None]:
    """Fill in missing results for emails from the last `days` days.

    - Emails whose classification failed (Further review, "classification failed") and that you haven't
      corrected are classified again from scratch: labels and stars.
    - Other emails without stars keep their stored topic and action (they may be your corrections) and
      only get the priority filled in.
    Stars you set yourself are always kept. Email bodies aren't stored, so they are re-read from Graph.
    """
    classifier = classifier or ClaudeClassifier(cfg)
    me = store.get_state(con, "my_address") or my_address(token)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    done = 0
    for m in list_inbox(token, _iso_z(since), max_n=5000):
        row = con.execute("SELECT topic, action, stars_auto, source, stars_user, visible FROM predictions "
                          "WHERE email_id=?", (m["id"],)).fetchone()
        if not row or (row[2] is not None and not include_rated):
            continue
        topic, action, _, source, stars_user, visible = row
        rec = to_record(m, me, cfg)
        corrected = con.execute("SELECT 1 FROM corrections WHERE email_id=? AND field IN ('topic','action')",
                                (m["id"],)).fetchone()
        if source == "fallback" and not corrected:
            r = classify(rec, cfg, classifier)
            if r.source == "fallback":
                if classifier.api_failed:
                    return done, classifier.last_error
                continue
            store.save(con, rec, r, classifier.model, bool(visible))
            if stars_user is not None:
                con.execute("UPDATE predictions SET stars_user=? WHERE email_id=?", (stars_user, m["id"]))
                con.commit()
            done += 1
            continue
        out = classifier(rec.text, rec.received)
        if out is None:
            if classifier.api_failed:
                return done, classifier.last_error
            continue
        if out.priority is None:
            continue
        r = Result(topic, action, out.confidence, "claude", factors=out.priority)
        r.priority = compute(topic, action, out.priority, rec.received, cfg)
        store.update_priority(con, m["id"], r)
        done += 1
    return done, None


def main():
    import argparse

    from . import graph_token
    from .config import get_config

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reclassify", action="store_true",
                    help="add stars to emails that have none and redo failed classifications")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--all", action="store_true", help="with --reclassify: also redo emails that have stars")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg, con, token = get_config(), store.connect(), graph_token.get()
    if args.reclassify:
        n, err = reclassify_priority(con, cfg, token, args.days, include_rated=args.all)
        print(f"Updated {n} emails." + (f" Stopped early: {err}" if err else ""))
    else:
        rep = sync_once(con, cfg, token)
        print(f"Labelled {rep.labelled} new emails; {rep.remaining} waiting for the next sync."
              + (f" Last error: {rep.last_error}" if rep.last_error else ""))


if __name__ == "__main__":
    main()
