"""The pasted Microsoft Graph access token (copied from Graph Explorer).

No Azure app registration is needed. The token belongs to your own account, lasts about an hour,
and cannot be refreshed, so you paste a new one when it expires.

Where the token is read from, in order:
  1. data/graph_token.txt  (written by the dashboard's "Paste token" box or `python -m src.graph_token`)
  2. GRAPH_TOKEN in .env

Treat the token like a password: anyone holding it can read your mail until it expires.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import time
from dataclasses import dataclass

from .config import DATA

TOKEN_FILE = DATA / "graph_token.txt"
READ_SCOPES = {"Mail.Read", "Mail.ReadWrite"}  # either lets us read bodies; this app only ever sends GETs


class TokenExpired(Exception):
    """Raised when Graph rejects the token. Paste a new one."""


@dataclass
class TokenInfo:
    present: bool
    expires_at: float | None = None   # unix time, if the token can be decoded
    scopes: set[str] | None = None
    account: str | None = None

    @property
    def minutes_left(self) -> float | None:
        return None if self.expires_at is None else (self.expires_at - time.time()) / 60

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time() + 30

    @property
    def can_read_mail(self) -> bool | None:
        return None if self.scopes is None else bool(self.scopes & READ_SCOPES)


def clean(raw: str) -> str:
    t = (raw or "").strip().strip('"').strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return "".join(t.split())  # remove line breaks from copy-paste


def save(raw: str) -> TokenInfo:
    token = clean(raw)
    if token.count(".") != 2:
        raise ValueError("That doesn't look like an access token. Copy it from Graph Explorer's 'Access token' tab.")
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return inspect(token)


def load() -> str | None:
    if TOKEN_FILE.exists():
        t = clean(TOKEN_FILE.read_text())
        if t:
            return t
    return clean(os.environ.get("GRAPH_TOKEN", "")) or None


def clear() -> None:
    TOKEN_FILE.unlink(missing_ok=True)


def inspect(token: str | None) -> TokenInfo:
    """Read expiry and scopes from the token without verifying it (display only)."""
    if not token:
        return TokenInfo(present=False)
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return TokenInfo(
            present=True,
            expires_at=float(claims["exp"]) if "exp" in claims else None,
            scopes=set(str(claims.get("scp", "")).split()) or None,
            account=claims.get("upn") or claims.get("unique_name") or claims.get("preferred_username"),
        )
    except Exception:
        return TokenInfo(present=True)


def get() -> str:
    """Return a usable token or raise TokenExpired with a clear instruction."""
    token = load()
    info = inspect(token)
    if not info.present:
        raise TokenExpired("No Graph token. Paste one in the dashboard or run `python -m src.graph_token`.")
    if info.expired:
        raise TokenExpired("The Graph token has expired. Paste a new one from Graph Explorer.")
    return token


if __name__ == "__main__":
    print("Paste the access token from Graph Explorer (input is hidden), then press Enter:")
    info = save(getpass.getpass(""))
    left = f"{info.minutes_left:.0f} minutes" if info.minutes_left is not None else "unknown time"
    print(f"Saved. Account: {info.account or 'unknown'}. Valid for about {left}.")
    if info.can_read_mail is False:
        print("Warning: this token has no Mail.Read permission. In Graph Explorer, open "
              "'Modify permissions', consent to Mail.Read, then copy a fresh token.")
