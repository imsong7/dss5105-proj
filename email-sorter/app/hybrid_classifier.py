"""Hybrid backends: classical-ML category plus text-encoder or Claude action."""

from __future__ import annotations

from pathlib import Path

from .encoder_classifier import EncoderClassifier
from .backends import BaseClassifier
from .claude_classifier import ClaudeClassifier
from .ml_classifier import MLClassifier
from .schemas import Classification, Email


class HybridClassifier(BaseClassifier):
    """Content category from the classical TF-IDF model, reply nature from an encoder.

    Loading is per task, so the unused halves (ML action pipeline, encoder
    category head) are never loaded and the hybrid only pays for the models it
    uses.
    """

    name = "hybrid"

    def __init__(
        self,
        models_dir: Path | str | None = None,
        encoder_models_dir: str | None = None,
    ):
        self._category = MLClassifier(models_dir=models_dir, tasks=("category",))
        self._action = EncoderClassifier(
            models_dir=encoder_models_dir, tasks=("action",)
        )

    @property
    def model_name(self) -> str:
        return f"{self._category.model_name} + {self._action.model_name}"

    @property
    def available(self) -> bool:
        return self._action.available

    def classify(self, email: Email) -> Classification:
        category = self._category.predict_category(email)
        action = self._action.predict_action(email)
        return Classification(
            content_category=category,
            reply_nature=action,
            deadline=None,
            reason="Hybrid: ML category + text-encoder action head.",
        )


class HybridClaudeClassifier(BaseClassifier):
    """Content category from the TF-IDF model, reply nature from Claude."""

    name = "hybrid_claude"

    def __init__(self, models_dir: Path | str | None = None):
        self._category = MLClassifier(models_dir=models_dir, tasks=("category",))
        self._action = ClaudeClassifier()

    @property
    def model_name(self) -> str:
        return f"{self._category.model_name} + {self._action.model_name}"

    def classify(self, email: Email) -> Classification:
        category = self._category.predict_category(email)
        action = self._action.classify(email)
        return Classification(
            content_category=category,
            reply_nature=action.reply_nature,
            deadline=action.deadline,
            reason=f"Hybrid: ML category + Claude action ({action.reason})",
        )
