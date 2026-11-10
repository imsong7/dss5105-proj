"""Display names the student chose for themselves.

A name set in the app wins over the one given when the account was created.
Stored per account in ``private/profiles.json``.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from .config import ROOT
from .jsonfile import read_json, write_json_atomic

PROFILES_PATH = ROOT / "private" / "profiles.json"
NAME_LIMIT = 40


class ProfileError(ValueError):
    """The name is not valid; the message is safe to show."""


def clean_name(value) -> str:
    name = " ".join(str(value or "").split())
    if len(name) > NAME_LIMIT:
        raise ProfileError(f"Use a name of at most {NAME_LIMIT} characters.")
    if any(ord(char) < 32 for char in name):
        raise ProfileError("The name has characters that are not allowed.")
    return name


class ProfileStore:
    def __init__(self, path: Path = PROFILES_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def name(self, owner: str) -> str:
        with self._lock:
            data = read_json(self.path, {})
        return str(data.get(owner, {}).get("name", ""))

    def set_name(self, owner: str, value) -> str:
        """Save a name. An empty name clears it."""
        name = clean_name(value)
        with self._lock:
            data = read_json(self.path, {})
            if name:
                data.setdefault(owner, {})["name"] = name
            else:
                data.get(owner, {}).pop("name", None)
            write_json_atomic(self.path, data)
        return name

    def source(self, owner: str) -> str:
        """The mail source this student picked, or "" for the app default."""
        with self._lock:
            data = read_json(self.path, {})
        value = str(data.get(owner, {}).get("source", ""))
        return value if value in MAIL_SOURCES else ""

    def set_source(self, owner: str, value) -> str:
        source = str(value or "").strip().lower()
        if source not in MAIL_SOURCES:
            raise ProfileError("Choose Power Automate or an Outlook token.")
        with self._lock:
            data = read_json(self.path, {})
            data.setdefault(owner, {})["source"] = source
            write_json_atomic(self.path, data)
        return source


# How a signed-in student's mail reaches the app: their own Power Automate
# flow pushes it, or they paste a short-lived Outlook (Graph) token.
MAIL_SOURCES = ("powerautomate", "outlook")

profile_store = ProfileStore()
