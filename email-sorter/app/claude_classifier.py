"""Claude backend through the inbox-sorter pipeline.

The inbox-sorter is a separate project with its own ``src`` package, so it is
loaded under an alias (``inbox_sorter``) instead of being put on ``sys.path``.
Its ``src`` name would otherwise shadow other packages in this repo.

The pipeline is kept intact: sender rules -> Claude API -> guardrails ->
fallback. This wrapper only translates the inbox-sorter labels into the
email-sorter taxonomy.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from .classifier_base import BaseClassifier
from .models import Classification, Email

INBOX_SORTER_DIR = Path(__file__).resolve().parents[2] / "inbox-sorter"
INBOX_ENV_PATH = INBOX_SORTER_DIR / ".env"
PACKAGE_ALIAS = "inbox_sorter"

TOPIC_ALIASES = {
    "fos general": "general",
    "general": "general",
    "career": "career",
    "medical": "medical",
    "promotions": "promotional",
    "promotional": "promotional",
    "canvas": "canva",
    "canva": "canva",
    "others": "others",
}

ACTION_ALIASES = {
    "needs a reply": "needs_reply",
    "needs reply": "needs_reply",
    "needs an action": "needs_action",
    "needs action": "needs_action",
    "reminder": "reminder",
    "no action needed": "no_immediate_action",
    "no immediate action": "no_immediate_action",
    "further review": "no_immediate_action",
}

DEFAULT_CATEGORY = "others"
DEFAULT_ACTION = "no_immediate_action"


def _normalise(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _load_package(alias: str = PACKAGE_ALIAS):
    """Import inbox-sorter/src under ``alias`` so its package names stay local."""
    package_dir = INBOX_SORTER_DIR / "src"
    init_file = package_dir / "__init__.py"
    if not init_file.is_file():
        raise RuntimeError(f"inbox-sorter package not found: {package_dir}")
    if alias in sys.modules:
        return sys.modules[alias]

    spec = importlib.util.spec_from_file_location(
        alias,
        init_file,
        submodule_search_locations=[str(package_dir)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(alias, None)
        raise
    return module


def load_inbox_modules() -> SimpleNamespace:
    """Return the inbox-sorter modules this backend needs."""
    _load_package()
    return SimpleNamespace(
        config=importlib.import_module(f"{PACKAGE_ALIAS}.config"),
        llm=importlib.import_module(f"{PACKAGE_ALIAS}.llm"),
        pipeline=importlib.import_module(f"{PACKAGE_ALIAS}.pipeline"),
        preprocess=importlib.import_module(f"{PACKAGE_ALIAS}.preprocess"),
    )


def claude_ready() -> bool:
    """Whether the app can call Claude: package installed and key present."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        from dotenv import dotenv_values

        return bool(dotenv_values(INBOX_ENV_PATH).get("ANTHROPIC_API_KEY"))
    except Exception:
        return False


class ClaudeClassifier(BaseClassifier):
    """Claude through the inbox-sorter pipeline (Anthropic API)."""

    name = "claude"

    def __init__(self, config_path: str | None = None, my_address: str = "") -> None:
        self.modules = load_inbox_modules()
        self.cfg = self.modules.config.get_config(config_path)
        self.my_address = my_address

        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "The Claude backend needs the 'anthropic' package. "
                "Install it with: pip install 'anthropic>=0.40'"
            ) from exc

        self.clf = self.modules.llm.ClaudeClassifier(self.cfg)
        if not self.clf.enabled:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set for the Claude backend. "
                f"Add it to {INBOX_ENV_PATH} (or export it) and retry."
            )

        self.mapping_notes = self._mapping_notes()

    @property
    def model_name(self) -> str:
        return getattr(self.clf, "model", "") or "claude"

    @property
    def max_chars(self) -> int:
        return int((self.cfg.get("preprocess") or {}).get("max_chars", 4000))

    def _mapping_notes(self) -> list[str]:
        """Report labels that cannot be mapped to the email-sorter taxonomy."""
        notes = []
        for topic in self.cfg.get("topics") or {}:
            if _normalise(topic) not in TOPIC_ALIASES:
                notes.append(f"unmapped topic {topic!r} -> {DEFAULT_CATEGORY}")
        for action in self.cfg.get("actions") or {}:
            if _normalise(action) not in ACTION_ALIASES:
                notes.append(f"unmapped action {action!r} -> {DEFAULT_ACTION}")
        return notes

    def map_topic(self, topic: str) -> str:
        return TOPIC_ALIASES.get(_normalise(topic), DEFAULT_CATEGORY)

    def map_action(self, action: str) -> str:
        return ACTION_ALIASES.get(_normalise(action), DEFAULT_ACTION)

    def _record(self, email: Email):
        """Build the inbox-sorter record for an email-sorter Email."""
        body = email.body or email.preview or ""
        message = {
            "id": str(email.id),
            "receivedDateTime": email.received or "",
            "subject": email.subject or "",
            "from": {"emailAddress": {"address": email.sender or "", "name": ""}},
            "toRecipients": [],
            "ccRecipients": [],
            "body": {"contentType": "text", "content": body},
            "webLink": "",
            "conversationId": "",
        }
        return self.modules.preprocess.to_record(message, self.my_address, self.cfg)

    def classify(self, email: Email) -> Classification:
        """Classify one email with the full inbox-sorter pipeline."""
        record = self._record(email)
        result = self.modules.pipeline.classify(record, self.cfg, self.clf)

        reason = result.reason or "inbox-sorter"
        if result.source == "fallback":
            error = getattr(self.clf, "last_error", None)
            if error:
                reason = f"{reason}: {error}"
        reason = f"{reason} (source: {result.source})"

        return Classification(
            content_category=self.map_topic(result.topic),
            reply_nature=self.map_action(result.action),
            deadline=None,
            reason=reason,
        )
