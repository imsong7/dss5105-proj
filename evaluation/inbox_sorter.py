"""Run the inbox-sorter as a benchmark backend.

The inbox-sorter is a self-contained project with its own ``src`` and ``app``
packages. Both names clash with the packages used by email-sorter (``app``) and
text-encoders (``src``), so its package is loaded under an alias
(``inbox_sorter``) instead of being put on ``sys.path``.

The adapter keeps the inbox-sorter's own pipeline intact -- sender rules ->
Claude API -> guardrails -> fallback -- and only translates the outcome into
the email-sorter taxonomy so all four methods can be compared in one table.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
INBOX_SORTER_DIR = REPO_ROOT / "inbox-sorter"
# The Anthropic API key lives here; inbox-sorter/src/config.py loads it.
INBOX_ENV_PATH = INBOX_SORTER_DIR / ".env"
PACKAGE_ALIAS = "inbox_sorter"

# inbox-sorter label -> email-sorter taxonomy key. The inbox-sorter labels are
# editable in config.yaml, so they are matched on a normalised name.
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
    # The inbox-sorter's fallback action has no email-sorter equivalent; the
    # classical ML mapping uses the same key.
    "further review": "no_immediate_action",
}

DEFAULT_CATEGORY = "others"
DEFAULT_ACTION = "no_immediate_action"


def _normalise(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _load_package(alias: str = PACKAGE_ALIAS):
    """Import inbox-sorter/src under `alias` so its package names stay local."""
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
    """Return the inbox-sorter modules the backend needs."""
    _load_package()
    return SimpleNamespace(
        config=importlib.import_module(f"{PACKAGE_ALIAS}.config"),
        llm=importlib.import_module(f"{PACKAGE_ALIAS}.llm"),
        pipeline=importlib.import_module(f"{PACKAGE_ALIAS}.pipeline"),
        preprocess=importlib.import_module(f"{PACKAGE_ALIAS}.preprocess"),
    )


@dataclass
class InboxResult:
    """One inbox-sorter decision, translated to the email-sorter taxonomy."""

    category: str
    action: str
    raw_valid: bool | None = None
    invalid_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    source: str = ""
    raw_excerpt: str = ""
    input_chars: int = 0


class InboxSorterBackend:
    """Classify emails with the inbox-sorter pipeline (Anthropic Claude API)."""

    name = "claude"

    def __init__(self, config_path: str | None = None, my_address: str = "") -> None:
        self.modules = load_inbox_modules()
        self.cfg = self.modules.config.get_config(config_path)
        self.my_address = my_address

        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError(
                "The inbox-sorter backend needs the 'anthropic' package. "
                "Install it with: pip install 'anthropic>=0.40'"
            ) from exc

        self.clf = self.modules.llm.ClaudeClassifier(self.cfg)
        if not self.clf.enabled:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set for the inbox-sorter backend. "
                f"Add it to {INBOX_ENV_PATH} (or export it) and retry. "
                "The key is read from that file by inbox-sorter/src/config.py."
            )

        self.mapping_notes = self._mapping_notes()

    # Configuration
    @property
    def model_name(self) -> str:
        return getattr(self.clf, "model", "") or "unknown"

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

    # Classification
    def _record(self, email) -> object:
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

    def map_topic(self, topic: str) -> str:
        return TOPIC_ALIASES.get(_normalise(topic), DEFAULT_CATEGORY)

    def map_action(self, action: str) -> str:
        return ACTION_ALIASES.get(_normalise(action), DEFAULT_ACTION)

    def _invalid_reason(self) -> str:
        """Why the last answer could not be used."""
        if getattr(self.clf, "last_stop_reason", None) == "max_tokens":
            return "max_tokens_truncated"
        error = getattr(self.clf, "last_error", None)
        if not error:
            return "empty_response"
        if "valid JSON" in error:
            return "invalid_json_or_label"
        return error[:120]

    def predict(self, email) -> InboxResult:
        """Classify one email with the full inbox-sorter pipeline."""
        record = self._record(email)
        result = self.modules.pipeline.classify(record, self.cfg, self.clf)

        raw = getattr(self.clf, "last_raw_text", "") or ""
        usage = getattr(self.clf, "last_usage", None) or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")

        if result.source == "shortcut":
            # A sender rule answered without an API call: no format to validate.
            raw_valid: bool | None = None
            invalid_reason: str | None = None
        elif raw:
            parsed = self.modules.llm.parse_labels(raw, self.cfg)
            raw_valid = parsed is not None
            invalid_reason = None if parsed is not None else self._invalid_reason()
        else:
            raw_valid = False
            invalid_reason = self._invalid_reason()

        excerpt = raw[:500].replace("\n", "\\n")
        return InboxResult(
            category=self.map_topic(result.topic),
            action=self.map_action(result.action),
            raw_valid=raw_valid,
            invalid_reason=invalid_reason,
            input_tokens=int(input_tokens) if input_tokens is not None else None,
            output_tokens=int(output_tokens) if output_tokens is not None else None,
            source=result.source,
            raw_excerpt=excerpt,
            input_chars=len(record.text),
        )
