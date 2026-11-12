"""A private ``.ics`` feed so deadlines show up in Google or Apple Calendar.

The browser app syncs the student's current deadlines here whenever mail is
loaded. The feed itself needs no login (calendar apps cannot sign in), so it is
protected by a long random token in the URL. Rotating the token cancels the old
link. Personal events are read from the event store when the feed is fetched.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from app.config import ROOT
from app.stores.jsonfile import read_json, write_json_atomic

FEED_PATH = ROOT / "private" / "feed.json"
MAX_ITEMS = 500
TIMEZONE = ZoneInfo("Asia/Singapore")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class FeedError(ValueError):
    """The synced data is not valid; the message is safe to show."""


def _clean_item(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip()[:300]
    title = str(raw.get("title") or "").strip()[:200]
    if not key or not title:
        return None
    try:
        day = date.fromisoformat(str(raw.get("date") or ""))
    except ValueError:
        return None
    time = str(raw.get("time") or "").strip()
    if time and not _TIME.match(time):
        time = ""
    url = str(raw.get("url") or "").strip()
    if not url.startswith(("https://", "http://")) or len(url) > 500:
        url = ""
    return {
        "key": key,
        "title": title,
        "date": day.isoformat(),
        "time": time,
        "detail": str(raw.get("detail") or "").strip()[:300],
        "url": url,
    }


class FeedStore:
    def __init__(self, path: Path = FEED_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def _read(self) -> dict:
        data = read_json(self.path, {})
        data.setdefault("tokens", {})
        data.setdefault("items", {})
        return data

    def token_for(self, owner: str) -> str:
        with self._lock:
            data = self._read()
            token = data["tokens"].get(owner)
            if not token:
                token = secrets.token_urlsafe(24)
                data["tokens"][owner] = token
                write_json_atomic(self.path, data)
            return token

    def rotate(self, owner: str) -> str:
        with self._lock:
            data = self._read()
            token = secrets.token_urlsafe(24)
            data["tokens"][owner] = token
            write_json_atomic(self.path, data)
            return token

    def owner_for(self, token: str) -> str | None:
        """The account a token belongs to, or ``None`` if it matches nothing."""
        with self._lock:
            tokens = self._read()["tokens"]
        found = None
        for owner, known in tokens.items():
            # Compare every token so timing does not reveal a near miss.
            if secrets.compare_digest(str(known), str(token)):
                found = owner
        return found

    def set_items(self, owner: str, raw_items) -> int:
        if not isinstance(raw_items, list):
            raise FeedError("Expected a list of items.")
        items = [item for item in map(_clean_item, raw_items[:MAX_ITEMS]) if item]
        with self._lock:
            data = self._read()
            data["items"][owner] = items
            write_json_atomic(self.path, data)
        return len(items)

    def items(self, owner: str) -> list[dict]:
        with self._lock:
            return list(self._read()["items"].get(owner, []))


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Lines longer than 75 bytes continue on the next line, indented."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    parts, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        limit = 75 if not parts else 74
        if len(current) + len(encoded) > limit:
            parts.append(current.decode("utf-8"))
            current = b""
        current += encoded
    parts.append(current.decode("utf-8"))
    return [parts[0], *[" " + part for part in parts[1:]]]


def _uid(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest() + "@inbox-sorter"


def build_ics(name: str, items: list[dict], now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//NusBox//Deadlines//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "X-WR-TIMEZONE:Asia/Singapore",
    ]

    for item in items:
        day = date.fromisoformat(item["date"])
        lines += ["BEGIN:VEVENT", f"UID:{_uid(item['key'])}", f"DTSTAMP:{stamp}"]

        if item.get("time"):
            hour, minute = map(int, item["time"].split(":"))
            start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TIMEZONE)
            end = start + timedelta(hours=1)
            lines.append("DTSTART:" + start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
            lines.append("DTEND:" + end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        else:
            lines.append("DTSTART;VALUE=DATE:" + day.strftime("%Y%m%d"))
            lines.append("DTEND;VALUE=DATE:" + (day + timedelta(days=1)).strftime("%Y%m%d"))

        lines.append("SUMMARY:" + _escape(item["title"]))
        if item.get("detail"):
            lines.append("DESCRIPTION:" + _escape(item["detail"]))
        if item.get("url"):
            lines.append("URL:" + item["url"])
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    folded = [piece for line in lines for piece in _fold(line)]
    return "\r\n".join(folded) + "\r\n"


feed_store = FeedStore()
