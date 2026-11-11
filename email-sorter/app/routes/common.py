"""State and small helpers shared by the route blueprints."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from flask import current_app, jsonify, request
from flask import session as flask_session

from app.accounts import authenticated_owner, is_token_session
from app.classifiers.backends import BaseClassifier
from app.config import settings
from app.stores import profiles


@dataclass
class SorterState:
    """Per-app state that used to live in ``create_app``'s closure."""

    default_backend: str | None
    mail_provider: str
    # The last webhook calls, so the dashboard can show what arrived.
    inbound_attempts: deque = field(default_factory=lambda: deque(maxlen=20))
    # One loaded classifier, swapped when another backend is asked for.
    classifier: BaseClassifier | None = None
    classifier_backend: str | None = None

    def backend_name(self, requested: str | None = None) -> str:
        return requested or self.default_backend or settings.model_backend


def sorter() -> SorterState:
    return current_app.extensions["sorter"]


def error(message: str, status: int):
    return jsonify({"error": message}), status


def request_user() -> str:
    """The authenticated dashboard account."""
    return authenticated_owner()


def account_for(owner: str) -> dict | None:
    return current_app.extensions.get("multiuser_accounts", {}).get(owner)


def token_session() -> bool:
    return sorter().mail_provider == "powerautomate" and is_token_session()


def mail_source(owner: str) -> str:
    """Where this student's mail comes from. Only accounts can choose."""
    provider = sorter().mail_provider
    if provider != "powerautomate" or not owner:
        return provider
    if token_session():
        return "outlook"
    return profiles.profile_store.source(owner) or provider


def display_name(owner: str) -> str:
    """A name chosen in the app, else the one given when the account was made."""
    chosen = profiles.profile_store.name(owner)
    if chosen:
        return chosen
    account = account_for(owner) or {}
    if not account and token_session():
        return str(flask_session.get("graph_name", "")).strip()
    return str(account.get("name", "")).strip()


def parse_datetime(value) -> datetime | None:
    """Parse an ISO 8601 string from the UI; ``None``/empty means "no bound"."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("Date bounds must be ISO 8601 strings.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 date: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_window(data: dict) -> tuple[datetime | None, datetime | None]:
    """``since``/``before`` from a request body. Raises ``ValueError`` with a message for the UI."""
    since = parse_datetime(data.get("since"))
    before = parse_datetime(data.get("before"))
    if since and before and since > before:
        raise ValueError("`since` must be earlier than `before`.")
    return since, before


def forwarded_proto() -> str:
    """The scheme the browser used (ngrok terminates HTTPS in front of the app)."""
    return request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()


def webhook_endpoint() -> str:
    return f"{forwarded_proto()}://{request.host}/api/inbound/outlook"
