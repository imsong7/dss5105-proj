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


class RefreshState:
    """What each account's flow has already delivered, so refreshes can be incremental.

    ``started`` is called when a refresh is sent to the flow. The flow ends with a call
    to ``done`` only if every step succeeded, so a half-finished run never counts as
    synced. After that, a later refresh only needs mail newer than ``synced_through``.
    """

    # Mail that arrived while a refresh was reading is covered by this overlap.
    MARGIN = timedelta(days=1)

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._lock = Lock()
        self._data: dict = read_json(self.path, {}) if self.path else {}

    def _save(self) -> None:
        if not self.path:
            return
        try:
            write_json_atomic(self.path, self._data)
        except Exception:
            log.exception("Could not save refresh state.")

    def started(self, owner: str, since: datetime, incremental: bool, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            rec = self._data.setdefault(normalize_owner(owner), {})
            rec["pending"] = {
                "since": _iso(since), "started": _iso(now), "incremental": incremental,
                "first_arrival": None, "received": 0,
            }

    def arrival(self, owner: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            pending = self._data.get(normalize_owner(owner), {}).get("pending")
            if pending:
                pending["received"] += 1
                pending["first_arrival"] = pending["first_arrival"] or _iso(now)

    def done(self, owner: str, now: datetime | None = None) -> dict | None:
        """Mark the pending refresh complete. Returns its timings, or ``None`` if none was pending."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            rec = self._data.setdefault(normalize_owner(owner), {})
            pending = rec.pop("pending", None)
            started = _when(pending["started"]) if pending else None
            if not pending or not started:
                return None
            first = _when(pending["first_arrival"])
            # An incremental run only covers newer mail: the covered start stays as before.
            rec["synced_since"] = rec["synced_since"] if pending["incremental"] and "synced_since" in rec else pending["since"]
            rec["synced_through"] = pending["started"]
            rec["last"] = {
                "incremental": pending["incremental"],
                "started": pending["started"],
                "done_at": _iso(now),
                "duration_s": round((now - started).total_seconds(), 1),
                "first_email_after_s": round((first - started).total_seconds(), 1) if first else None,
                "emails_pushed": pending["received"],
            }
            self._save()
            return dict(rec["last"])

    def last(self, owner: str) -> dict | None:
        with self._lock:
            last = self._data.get(normalize_owner(owner), {}).get("last")
            return dict(last) if last else None

    def incremental_since(self, owner: str, requested: datetime, has_mail: bool) -> datetime | None:
        """Newer start date for a refresh, or ``None`` when a full read is needed."""
        with self._lock:
            rec = self._data.get(normalize_owner(owner), {})
            synced_since = _when(rec.get("synced_since"))
            through = _when(rec.get("synced_through"))
        if not has_mail or not synced_since or not through:
            return None  # nothing delivered yet, or the saved mail is gone
        if requested < synced_since - self.MARGIN:
            return None  # the window grew: older mail was never read
        newer = through - self.MARGIN
        return newer if newer > requested else None


refresh_state = RefreshState(settings.refresh_state_file or None)
