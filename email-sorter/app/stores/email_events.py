"""What Claude found in each email: an event or deadline, or nothing.

One answer per (account, email id), kept in ``private/email_events.json`` so an
email is read by Claude only once, even after a restart. Failures (no key, network)
are never stored, so they are tried again later.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Lock

from app.config import ROOT
from app.stores.jsonfile import read_json, write_json_atomic

SCAN_PATH = ROOT / "private" / "email_events.json"
MAX_ENTRIES = 5000


def _key(owner: str, email_id: str) -> str:
    return hashlib.sha256(f"{owner}\n{email_id}".encode()).hexdigest()[:32]


class EmailEventStore:
    def __init__(self, path: Path = SCAN_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def get(self, owner: str, email_id: str) -> tuple[bool, dict | None]:
        """``(known, event)``; ``event`` is ``None`` when Claude found nothing."""
        with self._lock:
            data = read_json(self.path, {})
        key = _key(owner, email_id)
        return (key in data, data.get(key))

    def put(self, owner: str, email_id: str, event: dict | None) -> None:
        with self._lock:
            data = read_json(self.path, {})
            if len(data) >= MAX_ENTRIES:
                data = dict(list(data.items())[MAX_ENTRIES // 2 :])  # drop the oldest half
            data[_key(owner, email_id)] = event
            write_json_atomic(self.path, data)


email_event_store = EmailEventStore()
