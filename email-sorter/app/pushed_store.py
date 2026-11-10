"""In-memory inbox for emails pushed by Power Automate.

Several people can share one running app, so every message is stored under the
owner who pushed it (the dashboard email address). The dashboard only asks for
its own owner. Each owner keeps their newest ``max_items`` (so one person's flow
can never push out someone else's mail), with a hard cap across everyone to
bound memory. Deduplicate on ``(owner, message id)`` so Power Automate retries
do not create copies.
"""

from collections import OrderedDict
from threading import Lock

from .config import settings
from .schemas import Email


def normalize_owner(value) -> str:
    """Owners are compared case-insensitively and without surrounding space."""
    return str(value or "").strip().lower()


# Hard cap across all owners, as a multiple of the per-owner cap.
TOTAL_FACTOR = 50


class PushedStore:
    def __init__(self, max_items: int = 500):
        self.max_items = max(1, int(max_items))
        self.max_total = self.max_items * TOTAL_FACTOR
        self._items: OrderedDict[tuple[str, str], Email] = OrderedDict()
        self._lock = Lock()

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

    def owners(self) -> list[str]:
        """Owner addresses currently holding mail, newest first."""
        with self._lock:
            seen = []
            for item_owner, _ in reversed(self._items):
                if item_owner not in seen:
                    seen.append(item_owner)
            return seen

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


pushed_store = PushedStore(settings.inbound_max_emails)
