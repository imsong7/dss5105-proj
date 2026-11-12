"""Inbox for emails pushed by Power Automate (in memory, saved to disk).

Several people can share one running app, so every message is stored under the
owner who pushed it (the dashboard email address). The dashboard only asks for
its own owner. Each owner keeps their newest ``max_items`` (so one person's flow
can never push out someone else's mail), with a hard cap across everyone to
bound memory. Deduplicate on ``(owner, message id)`` so Power Automate retries
do not create copies.
"""

import atexit
import logging
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Timer

from app.config import settings
from app.schemas import Email
from app.stores.jsonfile import read_json, write_json_atomic

log = logging.getLogger(__name__)
SAVE_DELAY_S = 1.0  # pushes arrive in bursts: save once after the burst, not per email


def normalize_owner(value) -> str:
    """Owners are compared case-insensitively and without surrounding space."""
    return str(value or "").strip().lower()


# Hard cap across all owners, as a multiple of the per-owner cap.
TOTAL_FACTOR = 50


class PushedStore:
    def __init__(self, max_items: int = 500, path: Path | str | None = None):
        self.max_items = max(1, int(max_items))
        self.max_total = self.max_items * TOTAL_FACTOR
        self._items: OrderedDict[tuple[str, str], Email] = OrderedDict()
        self._lock = Lock()
        # Held while taking a snapshot AND writing it, so an older snapshot can
        # never be written after a newer one.
        self._write_lock = Lock()
        self.path = Path(path) if path else None
        self._timer: Timer | None = None
        if self.path:
            self._load()
            atexit.register(self.flush)

    def _load(self) -> None:
        """Bring back saved mail. A broken file or row is skipped, never fatal."""
        for row in read_json(self.path, []):
            try:
                email = Email.model_validate(row["email"])
                email._ocr_checked = bool(row.get("ocr_checked"))
                self._items[(normalize_owner(row["owner"]), email.id)] = email
            except Exception:
                log.warning("Skipped an unreadable saved email.")

    def _schedule_save(self) -> None:
        """Call with the lock held. One save per burst of pushes."""
        if not self.path or self._timer is not None:
            return
        self._timer = Timer(SAVE_DELAY_S, self.flush)
        self._timer.daemon = True
        self._timer.start()

    def flush(self) -> None:
        """Write everything to disk now. Never raises: saving must not break a push."""
        if not self.path:
            return
        with self._write_lock:
            with self._lock:
                self._timer = None
                rows = [
                    {"owner": owner, "email": email.model_dump(), "ocr_checked": email._ocr_checked}
                    for (owner, _), email in self._items.items()
                ]
            try:
                write_json_atomic(self.path, rows)
            except Exception:
                log.exception("Could not save pushed mail.")

    def add(self, email: Email, owner: str = "") -> tuple[Email, bool]:
        """Store ``email`` for ``owner`` and return ``(email, duplicate)``."""
        owner = normalize_owner(owner)
        with self._lock:
            key = (owner, email.id)
            existing = self._items.get(key)
            if existing is not None:
                return existing, True
            self._items[key] = email
            while sum(1 for item_owner, _ in self._items if item_owner == owner) > self.max_items:
                self._items.pop(self._oldest_key(owner))
            while len(self._items) > self.max_total:
                self._items.pop(self._oldest_key())
            self._schedule_save()
            return email, False

    def _oldest_key(self, owner: str | None = None) -> tuple[str, str]:
        """Evict by received date, not arrival order, when the queue is full.

        With ``owner``, only that owner's mail is considered.
        """
        keys = [key for key in self._items if owner is None or key[0] == owner]
        oldest_key = keys[0]
        oldest = None
        for key in keys:
            received = self._items[key].received_at
            if received is not None and (oldest is None or received < oldest):
                oldest = received
                oldest_key = key
        return oldest_key

    def all(self, owner: str = "") -> list[Email]:
        """Newest first, limited to mail pushed for ``owner``."""
        owner = normalize_owner(owner)
        with self._lock:
            return [email for (item_owner, _), email in reversed(self._items.items())
                    if item_owner == owner]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._schedule_save()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


pushed_store = PushedStore(settings.inbound_max_emails, settings.pushed_mail_file or None)


class PushedImages:
    """Inline images that came with pushed mail, kept until they are read.

    Stored as ``(name, bytes)`` pairs per account and email, newest kept. The
    bytes are dropped once OCR and the poster preview have used them.
    """

    def __init__(self, limit: int = 300):
        self.limit = limit
        self._items: "OrderedDict[tuple[str, str], list[tuple[str, bytes]]]" = OrderedDict()
        self._lock = Lock()

    def put(self, owner: str, email_id: str, images: list[tuple[str, bytes]]) -> None:
        if not images:
            return
        key = (normalize_owner(owner), email_id)
        with self._lock:
            self._items[key] = list(images)
            self._items.move_to_end(key)
            while len(self._items) > self.limit:
                self._items.popitem(last=False)

    def get(self, owner: str, email_id: str) -> list[tuple[str, bytes]]:
        with self._lock:
            return list(self._items.get((normalize_owner(owner), email_id), []))

    def drop(self, owner: str, email_id: str) -> None:
        with self._lock:
            self._items.pop((normalize_owner(owner), email_id), None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


pushed_images = PushedImages()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _when(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_SLACK = timedelta(days=1)  # time zones: Outlook may compare dates in local time


def _outside(received: datetime | None, since: str, before: str) -> bool:
    """Is ``received`` clearly outside the slice ``[since, before]`` (whole dates, with a day of slack)?"""
    if received is None:
        return False
    day = received.astimezone(timezone.utc).date()
    try:
        if since and day < datetime.fromisoformat(since).date() - _SLACK:
            return True
        if before and day > datetime.fromisoformat(before).date() + _SLACK:
            return True
    except ValueError:
        return False
    return False


class RefreshState:
    """Refresh runs of each account's flow, and how much of the mailbox is known to be synced.

    A run gets an id before the flow is called; the flow sends that id with every
    pushed email and with its final "done" call, and calls "done" only when every
    push succeeded (delivery). Each pushed email also says which date slice it came
    from and that slice's ``top`` limit. A slice that returned as many emails as its
    limit may have left older mail behind (retrieval may be incomplete), so such a
    run is reported as incomplete and does not move the incremental checkpoint.

    Saved state per owner: ``synced_since``/``synced_through`` (the requested window
    known complete) and ``last`` (the last run's report). Runs in progress live in
    memory only: after a restart their callbacks are treated as stale.
    """

    # Mail that arrived while a refresh was reading is covered by this overlap.
    # It only widens later queries; it is never recorded as synced coverage.
    MARGIN = timedelta(days=1)
    # A run whose "done" call has not come by then counts as lost; a new one may start.
    PENDING_TIMEOUT = timedelta(minutes=15)

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._lock = Lock()
        self._data: dict = read_json(self.path, {}) if self.path else {}
        self._pending: dict[str, dict] = {}

    def _save(self) -> None:
        """Call with the lock held, so snapshots are written in order."""
        if not self.path:
            return
        try:
            write_json_atomic(self.path, self._data)
        except Exception:
            log.exception("Could not save refresh state.")

    def _live_pending(self, owner: str, now: datetime) -> dict | None:
        """The run in progress, or ``None``; a run past the timeout is closed as lost."""
        pending = self._pending.get(owner)
        if pending and now - _when(pending["started"]) > self.PENDING_TIMEOUT:
            self._finish(owner, pending, now, status="timed_out")
            return None
        return pending

    def _finish(self, owner: str, pending: dict, now: datetime, status: str, **extra) -> dict:
        started = _when(pending["started"])
        first = _when(pending["first_arrival"])
        rec = self._data.setdefault(owner, {})
        rec["last"] = {
            "refresh_id": pending["id"],
            "status": status,
            "incremental": pending["incremental"],
            "started": pending["started"],
            "ended": _iso(now),
            "duration_s": round((now - started).total_seconds(), 1),
            "first_email_after_s": round((first - started).total_seconds(), 1) if first else None,
            "emails_pushed": len(pending["ids"]),
            **extra,
        }
        self._pending.pop(owner, None)
        self._save()
        return dict(rec["last"])

    def begin(self, owner: str, requested: datetime, incremental: bool,
              now: datetime | None = None) -> tuple[str, bool]:
        """Start a run (before the flow is called). Returns ``(refresh_id, created)``.

        ``requested`` is the window start the student asked for, recorded as coverage
        if the run completes; the query sent to the flow may start later (incremental).
        A run already in progress is returned instead of starting a second one.
        """
        now = now or datetime.now(timezone.utc)
        owner = normalize_owner(owner)
        with self._lock:
            pending = self._live_pending(owner, now)
            if pending:
                return pending["id"], False
            refresh_id = uuid.uuid4().hex
            self._pending[owner] = {
                "id": refresh_id, "requested": _iso(requested), "started": _iso(now),
                "incremental": incremental, "first_arrival": None, "ids": {}, "slices": {},
                "legacy_pushes": 0,
            }
            return refresh_id, True

    def failed(self, owner: str, refresh_id: str, reason: str, now: datetime | None = None) -> None:
        """The flow could not be started: close the run without touching coverage."""
        now = now or datetime.now(timezone.utc)
        owner = normalize_owner(owner)
        with self._lock:
            pending = self._pending.get(owner)
            if pending and pending["id"] == refresh_id:
                self._finish(owner, pending, now, status="failed", reason=reason)

    def arrival(self, owner: str, email_id: str, refresh_id: str | None = None,
                slice_info: dict | None = None, now: datetime | None = None,
                received: datetime | None = None) -> None:
        """Count one pushed email towards the run it belongs to (stale ids are ignored)."""
        now = now or datetime.now(timezone.utc)
        owner = normalize_owner(owner)
        with self._lock:
            pending = self._live_pending(owner, now)
            if not pending:
                return
            if refresh_id is None:
                pending["legacy_pushes"] += 1  # a flow imported before refresh ids existed
            elif refresh_id != pending["id"]:
                return
            pending["first_arrival"] = pending["first_arrival"] or _iso(now)
            pending["ids"][email_id] = True
            if refresh_id and slice_info and slice_info.get("index") is not None:
                bucket = pending["slices"].setdefault(
                    slice_info["index"], {"ids": {}, "outside": {}, "limit": None, "since": "", "before": ""}
                )
                bucket["ids"][email_id] = True
                for key in ("limit", "since", "before"):
                    if slice_info.get(key) not in (None, ""):
                        bucket[key] = slice_info[key]
                if _outside(received, bucket["since"], bucket["before"]):
                    bucket["outside"][email_id] = True

    def done(self, owner: str, refresh_id: str | None, now: datetime | None = None) -> dict:
        """The flow's final call. Returns ``{"status": ..., "refresh": report or None}``.

        ``delivered``: every retrieved email was pushed. ``complete``: no slice reached
        its limit. Only a delivered and complete run moves the synced window forward.
        """
        now = now or datetime.now(timezone.utc)
        owner = normalize_owner(owner)
        with self._lock:
            pending = self._pending.get(owner)  # a late but genuine "done" is still accepted
            if not pending:
                return {"status": "no_refresh", "refresh": None}
            if refresh_id is not None and refresh_id != pending["id"]:
                return {"status": "stale", "refresh": None}
            if refresh_id is None:
                # Old flow: it cannot say which run this was or whether a slice was cut off.
                report = self._finish(owner, pending, now, status="done", delivered=True,
                                      complete=None, slices=[],
                                      reason="flow has no refresh id; download and import it again")
                return {"status": "unverified", "refresh": report}

            slices = []
            for index, bucket in sorted(pending["slices"].items()):
                count, limit = len(bucket["ids"]), bucket["limit"]
                slices.append({
                    "index": index, "count": count, "limit": limit,
                    "truncated": limit is None or count >= limit,
                    # Mail dated outside the slice: Outlook did not apply the date range.
                    "outside": len(bucket.get("outside", {})),
                    "since": bucket["since"], "before": bucket["before"],
                })
            complete = not any(item["truncated"] or item["outside"] for item in slices)
            rec = self._data.setdefault(owner, {})
            if complete:
                # An incremental run only covers newer mail: the covered start stays as before.
                if not (pending["incremental"] and "synced_since" in rec):
                    rec["synced_since"] = pending["requested"]
                rec["synced_through"] = pending["started"]
                # Checkpoints saved by older versions never checked for cut-off slices.
                rec["verified"] = True
            report = self._finish(owner, pending, now, status="done", delivered=True,
                                  complete=complete, slices=slices)
            return {"status": "ok", "refresh": report}

    def last(self, owner: str) -> dict | None:
        with self._lock:
            last = self._data.get(normalize_owner(owner), {}).get("last")
            return dict(last) if last else None

    def status(self, owner: str, now: datetime | None = None) -> dict:
        """What the dashboard shows: a run in progress (if any) and the last finished run."""
        now = now or datetime.now(timezone.utc)
        owner = normalize_owner(owner)
        with self._lock:
            pending = self._live_pending(owner, now)
            running = {
                "refresh_id": pending["id"], "started": pending["started"],
                "emails_pushed": len(pending["ids"]),
            } if pending else None
            last = self._data.get(owner, {}).get("last")
            return {"running": running, "last": dict(last) if last else None}

    def incremental_since(self, owner: str, requested: datetime, has_mail: bool) -> datetime | None:
        """Newer start date for a refresh, or ``None`` when a full read is needed."""
        with self._lock:
            rec = self._data.get(normalize_owner(owner), {})
            synced_since = _when(rec.get("synced_since"))
            through = _when(rec.get("synced_through"))
        if not has_mail or not synced_since or not through or not rec.get("verified"):
            return None  # nothing verified delivered yet, or the saved mail is gone
        if requested < synced_since - self.MARGIN:
            return None  # the window grew: older mail was never read
        newer = through - self.MARGIN
        return newer if newer > requested else None


refresh_state = RefreshState(settings.refresh_state_file or None)
