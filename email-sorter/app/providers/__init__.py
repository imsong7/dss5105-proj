from .base import AuthError, EmailProvider, InlineImage, ProviderError
from .graph import GraphProvider
from .imap import ImapProvider


def build_provider(kind: str, creds: dict) -> EmailProvider:
    """Add new mail sources here: one line per provider."""
    if kind == "outlook":
        return GraphProvider(creds.get("token", ""))
    if kind == "imap":
        return ImapProvider(
            creds.get("host", ""), creds.get("user", ""), creds.get("password", "")
        )
    raise ProviderError(f"Unknown provider: {kind}")


__all__ = ["build_provider", "AuthError", "InlineImage", "ProviderError", "EmailProvider"]
