"""Generate one reply draft for the dashboard with the ``llm-reply`` pipeline."""

from __future__ import annotations

import importlib.util
import os
import sys
from email.utils import parseaddr
from pathlib import Path
from types import ModuleType

from .schemas import Email

REPO = Path(__file__).resolve().parents[2]
LLM_REPLY_DIR = REPO / "llm-reply"
GENERATOR_PATH = LLM_REPLY_DIR / "generate_replies.py"


class ReplyDraftError(Exception):
    """A configuration or provider error that the API should report."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


_generator: ModuleType | None = None


def _load_generator() -> ModuleType:
    """Load ``llm-reply/generate_replies.py`` without making it a package."""
    global _generator
    if _generator is not None:
        return _generator
    if not GENERATOR_PATH.is_file():
        raise ReplyDraftError(
            "Reply drafting is not available: llm-reply/generate_replies.py is missing.",
            503,
        )

    module_name = "email_sorter_llm_reply"
    spec = importlib.util.spec_from_file_location(module_name, GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise ReplyDraftError("Reply drafting could not be loaded.", 503)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ReplyDraftError(f"Reply drafting could not be loaded: {exc}", 503) from exc

    # The shared key lives in llm-reply/.env during local development.
    module.load_dotenv(LLM_REPLY_DIR / ".env")
    _generator = module
    return module


def _config(generator: ModuleType):
    provider = (
        os.getenv("REPLY_LLM_PROVIDER")
        or os.getenv("LLM_PROVIDER")
        or "anthropic"
    ).lower()
    defaults = {
        "anthropic": ("https://api.anthropic.com", "claude-haiku-5-5", "ANTHROPIC_API_KEY"),
        "openai": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
        "ollama": ("http://localhost:11434/v1", "llama3.1", ""),
    }
    if provider not in defaults:
        raise ReplyDraftError(
            f"Unknown reply LLM provider '{provider}'. Use anthropic, openai, or ollama.",
            400,
        )

    default_base_url, default_model, key_name = defaults[provider]
    api_key = (
        os.getenv("REPLY_LLM_API_KEY")
        or os.getenv("LLM_API_KEY")
        or (os.getenv(key_name) if key_name else "")
        or ""
    )
    if provider != "ollama" and not api_key:
        raise ReplyDraftError(
            "Reply drafting is not configured. Set ANTHROPIC_API_KEY in "
            "llm-reply/.env or email-sorter/.env.",
            503,
        )

    try:
        max_tokens = int(os.getenv("REPLY_LLM_MAX_TOKENS", "800"))
        timeout = int(os.getenv("REPLY_LLM_TIMEOUT", "90"))
    except ValueError as exc:
        raise ReplyDraftError("Reply LLM settings must be integers.", 503) from exc

    return generator.LLMConfig(
        provider=provider,
        model=(
            os.getenv("REPLY_LLM_MODEL")
            or os.getenv("LLM_MODEL")
            or default_model
        ),
        api_key=api_key,
        base_url=(
            os.getenv("REPLY_LLM_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or default_base_url
        ).rstrip("/"),
        temperature=0.3,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def _owner_label(owner: str, owner_name: str) -> str:
    name = (owner_name or "").strip()
    if name:
        return name
    if owner:
        local = owner.split("@", 1)[0]
        return local.replace(".", " ").replace("_", " ").title()
    return "the mailbox owner"


def _sender_parts(sender: str) -> tuple[str, str]:
    name, address = parseaddr(sender or "")
    address = address.strip()
    if not address and "@" in (sender or ""):
        address = sender.strip()
    name = name.strip() or (address.split("@", 1)[0] if address else "there")
    return name, address


def generate_reply(email: Email, owner: str = "", owner_name: str = "") -> dict:
    """Return a reply draft and its guardrail metadata for one dashboard email."""
    generator = _load_generator()
    config = _config(generator)
    sender_name, sender_email = _sender_parts(email.sender)
    body = email.body or email.preview or ""
    recipient_name = _owner_label(owner, owner_name)

    llm_email = generator.Email(
        id=email.id,
        internet_message_id="",
        subject=email.subject or "(no subject)",
        sender_name=sender_name,
        sender_email=sender_email,
        to=[{"name": recipient_name, "address": owner}] if owner else [],
        received=email.received or "",
        body=body,
        reply_to=None,
    )
    system, user = generator.build_prompt(llm_email, recipient_name)
    try:
        reply = generator.call_llm(config, system, user)
    except Exception as exc:
        raise ReplyDraftError(f"Could not generate a reply: {exc}", 502) from exc
    if not reply.strip():
        raise ReplyDraftError("The model returned an empty reply.", 502)

    return {
        "reply": reply,
        "placeholders": generator.placeholders_in(reply),
        "guardrail_issues": generator.guardrail_issues(reply, llm_email),
        "provider": config.provider,
        "model": config.model,
    }
