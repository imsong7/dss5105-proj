"""Personal calendar events that a student adds by hand.

Events are stored per account in one JSON file under ``private/`` (git-ignored,
like the session secret). Every write replaces the file atomically, so a crash
cannot leave half a file. Only the account that created an event can read,
change or delete it.
"""

from __future__ import annotations

import re
import secrets
from datetime import date
from pathlib import Path
from threading import Lock

from .config import ROOT
from .jsonfile import read_json, write_json_atomic

EVENTS_PATH = ROOT / "private" / "events.json"
MAX_EVENTS_PER_OWNER = 500
TITLE_LIMIT = 120
NOTES_LIMIT = 500

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class EventError(ValueError):
    """The submitted event is not valid; the message is safe to show."""


def _clean(data) -> dict:
    if not isinstance(data, dict):
        raise EventError("Expected a JSON object.")

    title = str(data.get("title") or "").strip()
    if not title:
        raise EventError("Give the event a title.")
    if len(title) > TITLE_LIMIT:
        raise EventError(f"Title must be at most {TITLE_LIMIT} characters.")

    raw_date = str(data.get("date") or "").strip()
    try:
        parsed = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise EventError("Choose a valid date.") from exc

    time = str(data.get("time") or "").strip()
    if time and not _TIME.match(time):
        raise EventError("Time must look like 14:30.")

    notes = str(data.get("notes") or "").strip()
    if len(notes) > NOTES_LIMIT:
        raise EventError(f"Notes must be at most {NOTES_LIMIT} characters.")

    return {"title": title, "date": parsed.isoformat(), "time": time, "notes": notes}


class EventStore:
    def __init__(self, path: Path = EVENTS_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def _read(self) -> dict[str, list[dict]]:
        return read_json(self.path, {})

    def _write(self, data: dict[str, list[dict]]) -> None:
        write_json_atomic(self.path, data)

    def list(self, owner: str) -> list[dict]:
        with self._lock:
            return list(self._read().get(owner, []))

    def create(self, owner: str, data) -> dict:
        fields = _clean(data)
        with self._lock:
            store = self._read()
            events = store.setdefault(owner, [])
            if len(events) >= MAX_EVENTS_PER_OWNER:
                raise EventError(
                    f"You can keep at most {MAX_EVENTS_PER_OWNER} events. Delete some first."
                )
            event = {"id": secrets.token_hex(8), **fields}
            events.append(event)
            self._write(store)
            return event

    def update(self, owner: str, event_id: str, data) -> dict | None:
        fields = _clean(data)
        with self._lock:
            store = self._read()
            for event in store.get(owner, []):
                if event["id"] == event_id:
                    event.update(fields)
                    self._write(store)
                    return dict(event)
        return None

    def delete(self, owner: str, event_id: str) -> bool:
        with self._lock:
            store = self._read()
            events = store.get(owner, [])
            kept = [event for event in events if event["id"] != event_id]
            if len(kept) == len(events):
                return False
            store[owner] = kept
            self._write(store)
            return True


event_store = EventStore()
