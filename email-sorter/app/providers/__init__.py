from .base import AuthError, EmailProvider, InlineImage, MailQuery, ProviderError
from .graph import GraphProvider
from .pushed import PushedProvider


def build_provider(kind: str, creds: dict) -> EmailProvider:
    """Add new mail sources here: one line per provider."""
    if kind == "outlook":
        return GraphProvider(creds.get("token", ""))
    if kind == "powerautomate":
        return PushedProvider(creds.get("owner") or creds.get("user") or "")
    raise ProviderError(f"Unknown provider: {kind}")


__all__ = [
    "build_provider",
    "AuthError",
    "EmailProvider",
    "InlineImage",
    "MailQuery",
    "ProviderError",
]
