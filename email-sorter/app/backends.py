"""Shared interface and factory for classifier backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .schemas import Classification, Email


class BaseClassifier(ABC):
    @abstractmethod
    def classify(self, email: Email) -> Classification:
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError


BACKEND_INFO: dict[str, dict[str, str]] = {
    "hybrid_claude": {
        "label": "Hybrid (ML + Claude)",
        "kind": "hybrid",
        "description": "TF-IDF category model with Claude for the action.",
    },
    "hybrid": {
        "label": "Hybrid (ML + text encoder)",
        "kind": "hybrid",
        "description": "TF-IDF category model with the text-encoder action head.",
    },
    "llama": {
        "label": "Llama (Ollama)",
        "kind": "llm",
        "description": "Local LLM served through Ollama.",
    },
    "encoder": {
        "label": "Text encoders",
        "kind": "encoder",
        "description": "Frozen BGE, E5, or DistilBERT encoders with classification heads.",
    },
    "ml": {
        "label": "Classical ML",
        "kind": "ml",
        "description": "TF-IDF category and action pipelines.",
    },
    "claude": {
        "label": "Claude",
        "kind": "llm",
        "description": "Anthropic Claude with sender rules and guardrails.",
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
    if name == "encoder":
        from .encoder_classifier import EncoderClassifier  # noqa: PLC0415
        return EncoderClassifier()
    if name == "ml":
        from .ml_classifier import MLClassifier  # noqa: PLC0415
        return MLClassifier()
    if name == "hybrid":
        from .hybrid_classifier import HybridClassifier  # noqa: PLC0415
        return HybridClassifier()
    if name == "hybrid_claude":
        from .hybrid_classifier import HybridClaudeClassifier  # noqa: PLC0415
        return HybridClaudeClassifier()
    if name == "claude":
        from .claude_classifier import ClaudeClassifier  # noqa: PLC0415
        return ClaudeClassifier()

    available = ", ".join(list_backends())
    raise ValueError(f"Unknown model backend '{name}'. Available: {available}")
