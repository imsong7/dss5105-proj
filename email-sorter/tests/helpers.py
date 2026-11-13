"""Shared test helpers."""

from app.accounts import SESSION_OWNER_KEY


def sign_in_as(client, email: str | None) -> None:
    """Make ``client`` signed in as ``email`` (``None`` signs it out), as the login page would."""
    with client.session_transaction() as session:
        session.clear()
        if email:
            session[SESSION_OWNER_KEY] = email
