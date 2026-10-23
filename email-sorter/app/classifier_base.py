"""Abstract base class for all email classifiers.

Every classifier backend (Llama/Ollama, BERT, future ML models) implements
this interface so the app can swap them at runtime via configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Classification, Email


class BaseClassifier(ABC):
    """Contract: classify an Email and return a Classification."""

    @abstractmethod
    def classify(self, email: Email) -> Classification:
        """Return a Classification for the given email."""
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name (e.g. 'llama', 'bert')."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
# Add a new entry here (plus a matching branch in create_classifier) when a
# teammate contributes a model. The UI reads this registry at runtime, so no
# frontend changes are needed.
BACKEND_INFO: dict[str, dict[str, str]] = {
    "llama": {
        "label": "Llama (Ollama)",
        "kind": "llm",
        "description": "Local LLM served through Ollama.",
    },
    "bert": {
        "label": "BERT",
        "kind": "encoder",
        "description": "Frozen sentence encoder with logistic-regression heads.",
    },
}


def list_backends() -> list[str]:
    """Return available backend names, in display order."""
    return list(BACKEND_INFO)


def create_classifier(backend: str | None = None) -> BaseClassifier:
    """Create a classifier by backend name.

    Defaults to the first registered backend when ``backend`` is None.
    Raises ``ValueError`` for unknown names.
    """
    name = (backend or next(iter(BACKEND_INFO))).lower()

    if name == "llama":
        from .classifier import EmailClassifier  # noqa: PLC0415
        return EmailClassifier()
    if name == "bert":
        from .bert_classifier import BertClassifier  # noqa: PLC0415
        return BertClassifier()

    available = ", ".join(list_backends())
    raise ValueError(f"Unknown model backend '{name}'. Available: {available}")
