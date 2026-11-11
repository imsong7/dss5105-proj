"""Remembered classifications and the student's corrections.

``ClassifyCache`` keeps each model result per account, backend and email id, so
an email is only sent to the model once. ``CorrectionStore`` keeps the labels a
student fixed by hand. A correction always wins over a cached or fresh model
result, and the log doubles as a small labelled dataset for evaluation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.classifiers.sender_rules import sender_address
from app.config import ROOT
from app.stores.jsonfile import read_json, write_json_atomic
from app.taxonomy import CONTENT_CATEGORIES, REPLY_NATURE

CACHE_PATH = ROOT / "private" / "classifications.json"
CORRECTIONS_PATH = ROOT / "private" / "corrections.json"
SENDER_RULES_PATH = ROOT / "private" / "sender_rules.json"
MAX_RULES_PER_OWNER = 500
MAX_CACHED_PER_BACKEND = 2000
MAX_CORRECTIONS_PER_OWNER = 2000
PREVIEW_LIMIT = 500


class CorrectionError(ValueError):
    """The correction is not valid; the message is safe to show."""


class ClassifyCache:
    def __init__(self, path: Path = CACHE_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def get(self, owner: str, backend: str, email_id: str) -> dict | None:
        with self._lock:
            data = read_json(self.path, {})
        return data.get(owner, {}).get(backend, {}).get(email_id)

    def all_for(self, owner: str, backend: str) -> dict:
        """Every cached result of ``owner`` for ``backend`` (one file read)."""
        with self._lock:
            data = read_json(self.path, {})
        return dict(data.get(owner, {}).get(backend, {}))

    def put(self, owner: str, backend: str, email_id: str, result: dict) -> None:
        with self._lock:
            data = read_json(self.path, {})
            entries = data.setdefault(owner, {}).setdefault(backend, {})
            entries.pop(email_id, None)
            entries[email_id] = result
            while len(entries) > MAX_CACHED_PER_BACKEND:
                entries.pop(next(iter(entries)))
            write_json_atomic(self.path, data)


class CorrectionStore:
    def __init__(self, path: Path = CORRECTIONS_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def get(self, owner: str, email_id: str) -> dict | None:
        with self._lock:
            data = read_json(self.path, {})
        return data.get(owner, {}).get(email_id)

    def all_for(self, owner: str) -> dict:
        """Every correction of ``owner``, keyed by email id (one file read)."""
        with self._lock:
            data = read_json(self.path, {})
        return dict(data.get(owner, {}))

    def save(self, owner: str, payload) -> dict:
        if not isinstance(payload, dict) or not isinstance(payload.get("email"), dict):
            raise CorrectionError("Expected an email and the corrected labels.")

        email = payload["email"]
        email_id = str(email.get("id") or "").strip()
        if not email_id:
            raise CorrectionError("The email has no id.")

        category = str(payload.get("content_category") or "")
        action = str(payload.get("reply_nature") or "")
        if category not in CONTENT_CATEGORIES:
            raise CorrectionError("Choose a valid category.")
        if action not in REPLY_NATURE:
            raise CorrectionError("Choose a valid action.")

        original = payload.get("original") or {}
        record = {
            "id": email_id,
            "subject": str(email.get("subject") or "")[:300],
            "sender": str(email.get("sender") or "")[:300],
            "sender_key": sender_address(str(email.get("sender") or "")),
            "rule": False,
            "received": str(email.get("received") or "")[:64],
            "preview": str(email.get("preview") or email.get("body") or "")[:PREVIEW_LIMIT],
            "backend": str(payload.get("backend") or "")[:64],
            "original_category": str(original.get("content_category") or ""),
            "original_action": str(original.get("reply_nature") or ""),
            "content_category": category,
            "reply_nature": action,
            "corrected_at": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            data = read_json(self.path, {})
            records = data.setdefault(owner, {})
            records.pop(email_id, None)
            records[email_id] = record
            while len(records) > MAX_CORRECTIONS_PER_OWNER:
                records.pop(next(iter(records)))
            write_json_atomic(self.path, data)
        return record

    def mark_rule(self, owner: str, email_id: str) -> None:
        """Remember that this correction also created a sender rule."""
        with self._lock:
            data = read_json(self.path, {})
            record = data.get(owner, {}).get(email_id)
            if record is not None:
                record["rule"] = True
                write_json_atomic(self.path, data)

    def delete(self, owner: str, email_id: str) -> dict | None:
        """Remove a correction and return it, or ``None`` if there was none."""
        with self._lock:
            data = read_json(self.path, {})
            records = data.get(owner, {})
            record = records.pop(email_id, None)
            if record is None:
                return None
            write_json_atomic(self.path, data)
        return record


class SenderRuleStore:
    """"Always label mail from this sender like this", per account."""

    def __init__(self, path: Path = SENDER_RULES_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def all_for(self, owner: str) -> dict:
        """Every sender rule of ``owner``, keyed by sender (one file read)."""
        with self._lock:
            data = read_json(self.path, {})
        return dict(data.get(owner, {}))

    def get(self, owner: str, sender_key: str) -> dict | None:
        if not sender_key:
            return None
        with self._lock:
            data = read_json(self.path, {})
        return data.get(owner, {}).get(sender_key)

    def set(self, owner: str, sender_key: str, category: str, action: str) -> dict:
        if not sender_key:
            raise CorrectionError("This email has no sender address to remember.")
        if category not in CONTENT_CATEGORIES or action not in REPLY_NATURE:
            raise CorrectionError("Choose a valid category and action.")
        record = {
            "content_category": category,
            "reply_nature": action,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            data = read_json(self.path, {})
            rules = data.setdefault(owner, {})
            rules.pop(sender_key, None)
            rules[sender_key] = record
            while len(rules) > MAX_RULES_PER_OWNER:
                rules.pop(next(iter(rules)))
            write_json_atomic(self.path, data)
        return record

    def delete(self, owner: str, sender_key: str) -> bool:
        with self._lock:
            data = read_json(self.path, {})
            rules = data.get(owner, {})
            if sender_key not in rules:
                return False
            del rules[sender_key]
            write_json_atomic(self.path, data)
        return True


classify_cache = ClassifyCache()
correction_store = CorrectionStore()
sender_rule_store = SenderRuleStore()
