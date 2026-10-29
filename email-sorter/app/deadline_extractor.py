"""Extract explicit deadline dates without model inference."""

import re
from datetime import date, datetime, time
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from .models import Email

TIMEZONE = ZoneInfo("Asia/Singapore")
# Only real month names may follow the cue, so a word like "due" in
# "exam\ndue 13 Nov" is not mistaken for a month and does not hide the date.
MONTH_NAME = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?"
    r"|dec(?:ember)?)"
)
DATE_EVENT_PATTERN = re.compile(
    r"\b(?P<cue>(?:due|deadline|submit\s+by|submission\s+deadline)"
    r"|(?:(?:final|mid[- ]term|midterm|mock|make[- ]up|oral|practical)\s+)?"
    r"(?:exam(?:ination)?|test|quiz)(?:\s+date)?)"
    # Anything short of a digit may sit between the cue and the date ("due",
    # "deadline is now", "extended to"), but never a line break: that keeps a
    # subject cue like "Bob exam" from pulling in a date from the body.
    r"[^0-9\n]{0,40}"
    r"(?P<date>(?:\d{1,2}[ \t]+" + MONTH_NAME + r"(?:,?[ \t]+\d{4})?"
    r"|" + MONTH_NAME + r"[ \t]+\d{1,2}(?:,?[ \t]+\d{4})?))"
    r"(?:(?:[ \t]+at[ \t]+|[ \t]*,[ \t]*|[ \t]+)(?P<time>\d{1,2}:\d{2}(?:[ \t]*(?:am|pm))?"
    r"|\d{1,2}[ \t]*(?:am|pm)))?",
    re.IGNORECASE,
)


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


def _parse_date(value: str, year: int) -> date | None:
    value = re.sub(r"\s+", " ", value.replace(",", " ")).strip()
    has_year = bool(re.search(r"\b\d{4}\b", value))
    formats = ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y")
    date_text = value if has_year else f"{value} {year}"
    for format_string in formats:
        try:
            return datetime.strptime(date_text, format_string).date()
        except ValueError:
            continue
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


def extract_deadline(email: Email) -> dict | None:
    """Return a candidate for an explicit, parseable deadline or exam date."""
    content = "\n".join(filter(None, (email.subject, email.body, email.preview)))
    for match in DATE_EVENT_PATTERN.finditer(content):
        candidate = _candidate_from_match(match, email)
        if candidate is not None:
            return candidate
    return None


def _candidate_from_match(match: re.Match, email: Email) -> dict | None:
    date_text = match.group("date")
    has_year = bool(re.search(r"\b\d{4}\b", date_text))
    received = _received_date(email.received)
    if not has_year and received is None:
        return None

    parsed = _parse_date(date_text, received.year if received else 2000)
    if parsed is None:
        return None
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
