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
# Factory
# --------------------------------------------------------------------------- #
def list_backends() -> list[str]:
    """Return available backend names."""
    return ["bert", "llama"]


def create_classifier(backend: str | None = None) -> BaseClassifier:
    """Create a classifier instance by backend name.

    Falls back to the first registered backend if ``backend`` is None or
    unknown.
    """
    name = (backend or "llama").lower()

    if name == "llama":
        from .classifier import EmailClassifier  # noqa: PLC0415
        return EmailClassifier()
    if name == "bert":
        from .bert_classifier import BertClassifier  # noqa: PLC0415
        return BertClassifier()

    available = ", ".join(list_backends())
    raise ValueError(f"Unknown model backend '{name}'. Available: {available}")
