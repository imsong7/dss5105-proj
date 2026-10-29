"""Load the NUS academic calendar that sits beside the Canvas deadlines.

The CSV lives with the other shared data at the repository root, not inside the
Flask package, so the browser gets it through a small read-only endpoint.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .config import ROOT

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
