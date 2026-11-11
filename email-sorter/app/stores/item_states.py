"""Done and snoozed marks for the items shown on the Today view.

A key is an email id, or ``event:<id>`` for a personal calendar event. Marks
are kept per account in ``private/item_states.json``. Snoozing hides an item
until the chosen date; marking it done hides it until it is un-done.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock

from app.config import ROOT
from app.stores.jsonfile import read_json, write_json_atomic

STATES_PATH = ROOT / "private" / "item_states.json"
MAX_STATES_PER_OWNER = 3000
KEY_LIMIT = 300


class StateError(ValueError):
    """The submitted mark is not valid; the message is safe to show."""


class ItemStateStore:
    def __init__(self, path: Path = STATES_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def list(self, owner: str) -> dict[str, dict]:
        with self._lock:
            return dict(read_json(self.path, {}).get(owner, {}))

    def set(self, owner: str, payload) -> dict | None:
        """Store a mark. Returns ``None`` when it cleared the item's mark."""
        if not isinstance(payload, dict):
            raise StateError("Expected a JSON object.")

        key = str(payload.get("key") or "").strip()
        if not key or len(key) > KEY_LIMIT:
            raise StateError("Missing item key.")

        done = bool(payload.get("done"))
        snoozed = str(payload.get("snoozed_until") or "").strip()
        if snoozed:
            try:
                snoozed = date.fromisoformat(snoozed).isoformat()
            except ValueError as exc:
                raise StateError("Choose a valid snooze date.") from exc

        with self._lock:
            data = read_json(self.path, {})
            states = data.setdefault(owner, {})
            states.pop(key, None)
            if not done and not snoozed:
                write_json_atomic(self.path, data)
                return None
            record = {
                "done": done,
                "snoozed_until": snoozed,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            states[key] = record
            while len(states) > MAX_STATES_PER_OWNER:
                states.pop(next(iter(states)))
            write_json_atomic(self.path, data)
            return record


item_states = ItemStateStore()
