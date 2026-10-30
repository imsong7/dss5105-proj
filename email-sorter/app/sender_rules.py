"""Sender-based category overrides."""

import re
from email.utils import parseaddr

SENDER_RULES = {
    "category": {"notifications@instructure.com": "canva"},
}


def sender_address(sender: str) -> str:
    value = sender or ""
    address = parseaddr(value)[1].strip()
    if not address:
        match = re.search(r"<\s*([^<>\s]+@[^<>\s]+)\s*>", value)
        address = match.group(1) if match else ""
    return address.lower()


def category_by_rule(sender: str) -> str | None:
    """Return the matching category, if any."""
    return SENDER_RULES["category"].get(sender_address(sender))
