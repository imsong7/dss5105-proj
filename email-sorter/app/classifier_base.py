"""Shared interface and factory for classifier backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Classification, Email


class BaseClassifier(ABC):
    @abstractmethod
    def classify(self, email: Email) -> Classification:
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError


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
    return list(BACKEND_INFO)


def create_classifier(backend: str | None = None) -> BaseClassifier:
    """Create a classifier by backend name."""
    name = (backend or next(iter(BACKEND_INFO))).lower()

    if name == "llama":
        from .llama_classifier import EmailClassifier  # noqa: PLC0415
        return EmailClassifier()
    if name == "bert":
        from .bert_classifier import BertClassifier  # noqa: PLC0415
        return BertClassifier()

    available = ", ".join(list_backends())
    raise ValueError(f"Unknown model backend '{name}'. Available: {available}")
