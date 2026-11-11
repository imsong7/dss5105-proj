"""Calendar helpers for the dashboard.

Two sources feed the calendar tab:

- ``extract_deadline`` reads an explicit deadline or exam date from an email
  without model inference.
- ``load_academic_calendar`` reads the shared NUS calendar CSV that sits beside
  the email deadline candidates.

The CSV lives with the other shared data at the repository root, not inside the
Flask package, so the browser gets it through a small read-only endpoint.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import ROOT
from app.mail.text_utils import without_link_addresses
from app.schemas import Email

TIMEZONE = ZoneInfo("Asia/Singapore")

ACADEMIC_CALENDAR_PATH = (
    ROOT.parent / "data" / "nus_academic_calendar_AY2026_2027.csv"
)
ACADEMIC_CALENDAR_LABEL = "NUS AY2026/27"

_DEFAULT_FIELDS = {
    "category": "",
    "event": "",
    "start_date": "",
    "end_date": "",
    "scope": "",
    "mark": "",
    "notes": "",
}

# Only real month names may follow the cue, so a word like "due" in
# "exam\ndue 13 Nov" is not mistaken for a month and does not hide the date.
MONTH_NAME = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?"
    r"|dec(?:ember)?)"
)
_ORDINAL = r"(?:st|nd|rd|th)?"
# "8 November", "8th of November 2026", "8 - 15 Nov" (a range ends on its last day).
_DAY_MONTH = (
    r"(?:\d{1,2}" + _ORDINAL + r"[ \t]*(?:-|\u2013|\u2014|to|until)[ \t]*)?"
    r"\d{1,2}" + _ORDINAL + r"[ \t]+(?:of[ \t]+)?" + MONTH_NAME + r"(?:,?[ \t]+\d{4})?"
)
_MONTH_DAY = MONTH_NAME + r"[ \t]+\d{1,2}" + _ORDINAL + r"(?:,?[ \t]+\d{4})?"
_ISO_DATE = r"\d{4}-\d{2}-\d{2}"
# Day first, as in Singapore: 15/11/2026, 15.11.2026, 15-11-2026, 15/11/26.
_NUMERIC_DATE = r"\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2}(?!\d))"

# Words that say "this is the date it is due". "by" and "before" only count after
# a verb that asks the student to do something, so "posted by 5 Nov" is ignored.
_ACTION_VERB = (
    r"(?:submit(?:ted)?|register(?:ed)?|registration|apply|application|rsvp|reply|respond|"
    r"complete|sign[ \t]*up|enrol(?:ment)?|return|hand[ \t]*in|pay(?:ment)?|confirm|book|send|"
    r"upload|respond)"
)
_CUE = (
    r"\b(?P<cue>(?:due|deadline|closing[ \t]+date|closes?(?:[ \t]+on)?|closing(?:[ \t]+on)?"
    r"|submission[ \t]+deadline"
    r"|" + _ACTION_VERB + r"[ \t]+(?:is[ \t]+)?(?:by|before|on[ \t]+or[ \t]+before|deadline)"
    r")"
    r"|(?:(?:final|mid[- ]term|midterm|mock|make[- ]up|oral|practical)[ \t]+)?"
    r"(?:exam(?:ination)?|test|quiz)(?:[ \t]+date)?)"
)
_TIME = (
    r"(?:(?:[ \t]+at[ \t]+|[ \t]*,[ \t]*|[ \t]+)(?P<time>\d{1,2}:\d{2}(?:[ \t]*(?:am|pm))?"
    r"|\d{1,2}[ \t]*(?:am|pm)))?"
)
DATE_EVENT_PATTERN = re.compile(
    _CUE +
    # Anything short of a digit may sit between the cue and the date ("due",
    # "deadline is now", "extended to"), but never a line break: that keeps a
    # subject cue like "Bob exam" from pulling in a date from the body.
    r"[^0-9\n]{0,40}?"
    r"(?P<date>(?:" + _DAY_MONTH + r"|" + _MONTH_DAY + r"|" + _ISO_DATE + r"|" + _NUMERIC_DATE + r"))"
    + _TIME,
    re.IGNORECASE,
)

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# "due tomorrow 5pm", "exam this Friday", "submit by next Monday". A weekday that
# is followed by a written date ("Sunday, 8 November") is left to the pattern above.
RELATIVE_PATTERN = re.compile(
    _CUE +
    r"[^0-9\n]{0,25}?\b"
    r"(?:(?P<rel>today|tonight|tomorrow)"
    r"|(?:(?P<mod>this|next|coming)[ \t]+)?(?P<wd>mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?)\b"
    r"(?![ \t]*,?[ \t]*(?:\d{1,2}" + _ORDINAL + r"[ \t]+(?:of[ \t]+)?" + MONTH_NAME + r"|" + MONTH_NAME + r"\b))"
    + _TIME,
    re.IGNORECASE,
)

MAX_CANDIDATES = 6


# ---- academic calendar -----------------------------------------------------


def _marked(value: object) -> bool:
    """The CSV uses ``mark=1`` for ranges that need both boundary dates."""
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _iso_date(value: object) -> str | None:
    """Return an ISO date string only when the cell is a real date."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def load_academic_calendar(path: str | Path | None = None) -> list[dict]:
    """Read the academic CSV as sorted, validated events.

    A missing file or a malformed row should not break the dashboard, so both
    are skipped and the caller receives whatever valid rows remain.
    """
    target = Path(path) if path else ACADEMIC_CALENDAR_PATH
    try:
        handle = target.open("r", encoding="utf-8-sig", newline="")
    except OSError:
        return []

    events: list[dict] = []
    with handle:
        for row in csv.DictReader(handle):
            item = {**_DEFAULT_FIELDS, **{k: (v or "").strip() for k, v in row.items() if k}}
            start = _iso_date(item["start_date"])
            end = _iso_date(item["end_date"]) or start
            if not item["event"] or not start or not end or end < start:
                continue
            events.append(
                {
                    "category": item["category"] or "University",
                    "event": item["event"],
                    "start_date": start,
                    "end_date": end,
                    "scope": item["scope"],
                    "mark": _marked(item["mark"]),
                    "notes": item["notes"],
                }
            )

    events.sort(key=lambda event: (event["start_date"], event["end_date"], event["event"]))
    return events


# ---- deadline extraction --------------------------------------------------


def _received_date(value: str) -> date | None:
    if not value:
        return None
    try:
        received = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            received = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if received.tzinfo is None:
        received = received.replace(tzinfo=TIMEZONE)
    return received.astimezone(TIMEZONE).date()


_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_RE_NUMERIC = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})")
_RE_DAY_MONTH = re.compile(
    r"(\d{1,2})" + _ORDINAL + r"[ \t]+(?:of[ \t]+)?(" + MONTH_NAME + r")(?:[ \t]+(\d{4}))?", re.I
)
_RE_MONTH_DAY = re.compile(
    r"(" + MONTH_NAME + r")[ \t]+(\d{1,2})" + _ORDINAL + r"(?:[ \t]+(\d{4}))?", re.I
)


def _month_number(name: str) -> int:
    return _MONTHS[name[:3].lower()]


def _parse_date(value: str, year: int) -> tuple[date, bool] | None:
    """Return ``(date, year_was_written)`` or ``None`` when it is not a real date."""
    value = re.sub(r"\s+", " ", value.replace(",", " ")).strip()

    if found := _RE_ISO.fullmatch(value):
        year_text, month, day, written = found[1], found[2], found[3], True
    elif found := _RE_NUMERIC.fullmatch(value):
        day, month, year_text = found[1], found[2], found[3]
        year_text = year_text if len(year_text) == 4 else f"20{year_text}"
        written = True
    elif found := _RE_DAY_MONTH.search(value):
        day, month, year_text = found[1], str(_month_number(found[2])), found[3]
        written = year_text is not None
    elif found := _RE_MONTH_DAY.search(value):
        day, month, year_text = found[2], str(_month_number(found[1])), found[3]
        written = year_text is not None
    else:
        return None

    try:
        return date(int(year_text or year), int(month), int(day)), written
    except ValueError:
        return None


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value.strip()).upper()
    value = re.sub(r"(?<=\d)(AM|PM)$", r" \1", value)
    formats = ("%H:%M", "%I:%M %p", "%I %p")
    for format_string in formats:
        try:
            return datetime.strptime(value, format_string).time()
        except ValueError:
            continue
    return None


def extract_deadlines(email: Email) -> list[dict]:
    """Every explicit deadline or exam date in the email, in reading order.

    Subject and body often repeat the same date, so a date is listed once per
    kind. At most ``MAX_CANDIDATES`` are returned.
    """
    # Link addresses ("Submit<https://...> by Fri") would split a cue from its date.
    content = without_link_addresses(
        "\n".join(filter(None, (email.subject, email.body, email.preview)))
    )
    hits: list[tuple[int, dict]] = []

    for match in DATE_EVENT_PATTERN.finditer(content):
        candidate = _candidate_from_match(match, email)
        if candidate is not None:
            hits.append((match.start(), candidate))

    # "Friday" or "tomorrow" is only a fallback. When the email also writes a
    # real date, trust that: a weekday counted from the day it arrived is often
    # a different week (sent Saturday, "due Friday" in the subject, "8 Nov" in
    # the body).
    if not hits:
        for match in RELATIVE_PATTERN.finditer(content):
            candidate = _relative_candidate(match, email)
            if candidate is not None:
                hits.append((match.start(), candidate))

    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for _, candidate in sorted(hits, key=lambda hit: hit[0]):
        key = (candidate["date"], candidate["event_type"])
        if key in seen:
            continue
        seen.add(key)
        found.append(candidate)
        if len(found) == MAX_CANDIDATES:
            break

    return found


def _resolve_relative(match: re.Match, received: date) -> date | None:
    word = (match.group("rel") or "").lower()
    if word in ("today", "tonight"):
        return received
    if word == "tomorrow":
        return received + timedelta(days=1)

    target = _WEEKDAYS.index(
        next(day for day in _WEEKDAYS if day.startswith(match.group("wd").lower()[:3]))
    )
    modifier = (match.group("mod") or "").lower()
    if modifier == "next":
        # Next week's day: count from the coming Monday.
        monday = received + timedelta(days=7 - received.weekday())
        return monday + timedelta(days=target)
    # "Friday" or "this Friday": the next one on or after the day it was sent.
    return received + timedelta(days=(target - received.weekday()) % 7)


def _relative_candidate(match: re.Match, email: Email) -> dict | None:
    received = _received_date(email.received)
    if received is None:
        return None
    parsed = _resolve_relative(match, received)
    if parsed is None:
        return None

    parsed_time = _parse_time(match.group("time"))
    if match.group("time") and parsed_time is None:
        return None
    candidate = {
        "date": parsed.isoformat(),
        "all_day": parsed_time is None,
        "timezone": "Asia/Singapore",
        "text": match.group(0).strip(),
        # The date depends on the day the email arrived, so ask for a check.
        "year_inferred": True,
        "event_type": (
            "exam"
            if re.search(r"\b(?:exam|examination|test|quiz)\b", match.group("cue"), re.I)
            else "deadline"
        ),
    }
    if parsed_time is not None:
        candidate["due_at"] = datetime.combine(
            parsed, parsed_time, tzinfo=TIMEZONE
        ).isoformat()
    return candidate


def extract_deadline(email: Email) -> dict | None:
    """The first deadline in the email, or ``None``."""
    found = extract_deadlines(email)
    return found[0] if found else None


def _candidate_from_match(match: re.Match, email: Email) -> dict | None:
    date_text = match.group("date")
    received = _received_date(email.received)

    # Peek at whether a year is written before deciding if it can be inferred.
    probe = _parse_date(date_text, 2000)
    if probe is None:
        return None
    parsed, has_year = probe
    if not has_year:
        if received is None:
            return None
        parsed = _parse_date(date_text, received.year)[0]

    year_inferred = not has_year
    if year_inferred and parsed < received:
        try:
            parsed = parsed.replace(year=parsed.year + 1)
        except ValueError:
            return None

    parsed_time = _parse_time(match.group("time"))
    if match.group("time") and parsed_time is None:
        return None
    candidate = {
        "date": parsed.isoformat(),
        "all_day": parsed_time is None,
        "timezone": "Asia/Singapore",
        "text": match.group(0).strip(),
        "year_inferred": year_inferred,
        "event_type": (
            "exam"
            if re.search(r"\b(?:exam|examination|test|quiz)\b", match.group("cue"), re.I)
            else "deadline"
        ),
    }
    if parsed_time is not None:
        candidate["due_at"] = datetime.combine(
            parsed, parsed_time, tzinfo=TIMEZONE
        ).isoformat()
    return candidate
