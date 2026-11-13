"""Claude backend through the ``claude/`` pipeline.

The Claude backend is a separate project with its own ``src`` package, so it
is loaded under an alias instead of being put on ``sys.path``. Its ``src``
name would otherwise shadow other packages in this repo.

The pipeline is kept intact: sender rules -> Claude API -> guardrails ->
fallback. This wrapper only translates the Claude labels into the email-sorter
taxonomy.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
import time
from types import SimpleNamespace

from app.classifiers.backends import BaseClassifier
from app.classifiers.classification_metrics import log_event
from app.config import ROOT
from app.schemas import Classification, Email

CLAUDE_DIR = ROOT.parent / "claude"
CLAUDE_ENV_PATH = CLAUDE_DIR / ".env"
PACKAGE_ALIAS = "claude_backend"

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
    """Import claude/src under ``alias`` so its package names stay local."""
    package_dir = CLAUDE_DIR / "src"
    init_file = package_dir / "__init__.py"
    if not init_file.is_file():
        raise RuntimeError(f"claude package not found: {package_dir}")
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


def load_claude_modules() -> SimpleNamespace:
    """Return the Claude backend modules this backend needs."""
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

        return bool(dotenv_values(CLAUDE_ENV_PATH).get("ANTHROPIC_API_KEY"))
    except Exception:
        return False


class ClaudeClassifier(BaseClassifier):
    """Claude through the ``claude/`` pipeline (Anthropic API)."""

    name = "claude"

    def __init__(self, config_path: str | None = None, my_address: str = "", action_only: bool = False) -> None:
        self.modules = load_claude_modules()
        self.cfg = self.modules.config.get_config(config_path)
        self.my_address = my_address

        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "The Claude backend needs the 'anthropic' package. "
                "Install it with: pip install 'anthropic>=0.40'"
            ) from exc

        self.clf = self.modules.llm.ClaudeClassifier(self.cfg, action_only=action_only)
        if not self.clf.enabled:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set for the Claude backend. "
                f"Add it to {CLAUDE_ENV_PATH} (or export it) and retry."
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
        """Build the Claude backend record for an email-sorter Email."""
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

    @staticmethod
    def _priority(result) -> dict | None:
        """The star rating for the API, or None when Claude gave no usable factors."""
        rated = getattr(result, "priority", None)
        if rated is None:
            return None
        factors = result.factors
        return {
            "stars": rated.stars,
            "score": rated.score,
            "notes": list(rated.notes),
            "key_point": factors.key_point if factors else "",
            "suspicious": bool(factors and factors.suspicious),
            # What the stars were worked out from, so the page can say why (urgency is the
            # one actually used: counted from the deadline when the email has one).
            "consequence": factors.consequence if factors else None,
            "urgency": rated.urgency,
            "relevance": factors.relevance if factors else None,
            "deadline": factors.deadline if factors else None,
        }

    def classify(self, email: Email) -> Classification:
        """Classify one email with the full Claude backend pipeline."""
        t_preprocess = time.perf_counter()
        record = self._record(email)
        preprocess_ms = int((time.perf_counter() - t_preprocess) * 1000)

        result = self.modules.pipeline.classify(record, self.cfg, self.clf)

        t_postprocess = time.perf_counter()
        reason = result.reason or "claude"
        if result.source == "fallback":
            error = getattr(result, "error", None)  # this call's own error, not shared state
            if error:
                reason = f"{reason}: {error}"
        reason = f"{reason} (source: {result.source})"

        classification = Classification(
            content_category=self.map_topic(result.topic),
            reply_nature=self.map_action(result.action),
            deadline=None,
            reason=reason,
            priority=self._priority(result),
            event=getattr(result, "event", None),
            fallback=result.source == "fallback",
        )
        postprocess_ms = int((time.perf_counter() - t_postprocess) * 1000)

        log_event(
            "claude_api_call",
            api_called=getattr(result, "api_called", False),
            api_duration_ms=getattr(result, "api_duration_ms", None),
            input_tokens=getattr(result, "input_tokens", None),
            output_tokens=getattr(result, "output_tokens", None),
            stop_reason=getattr(result, "stop_reason", None),
            app_attempts=getattr(result, "app_attempts", 0),
            app_retry_attempts=getattr(result, "app_retry_attempts", 0),
            retry_call_ms=getattr(result, "retry_call_ms", 0),
            retry_backoff_ms=getattr(result, "retry_backoff_ms", 0),
            sdk_retries="unknown",
            sdk_retry_wait_ms="unknown",
            provider_prompt_cached=(getattr(result, "cache_read_tokens", None) or 0) > 0,
            cache_read_tokens=getattr(result, "cache_read_tokens", None),
            pipeline_source=result.source,
            error_type=getattr(result, "error_type", None),
        )
        log_event(
            "claude_preprocess",
            duration_ms=preprocess_ms,
        )
        log_event(
            "claude_postprocess",
            duration_ms=postprocess_ms,
        )

        return classification
