"""Text-encoder classifier wrapper for the trained encoder heads."""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
ENCODERS_DIR = os.path.join(REPO_ROOT, "text-encoders")
if ENCODERS_DIR not in sys.path:
    sys.path.insert(0, ENCODERS_DIR)

from .classifier_base import BaseClassifier
from .models import Classification, Email
from .taxonomy import CONTENT_CATEGORIES, DEFAULT_CONTENT, DEFAULT_REPLY, REPLY_NATURE

ENCODER_MODELS_DIR = os.path.join(ENCODERS_DIR, "models")

MODEL_DIRS = {
    "category": os.path.join(ENCODER_MODELS_DIR, "category_head"),
    "action": os.path.join(ENCODER_MODELS_DIR, "action_head"),
}


def _model_text(email: Email) -> str:
    """Use the full body when available, otherwise the preview."""
    body = (email.body or "").strip()
    preview = (email.preview or "").strip()
    return body or preview


class BertClassifier(BaseClassifier):
    """Load the trained category and action heads."""

    name = "bert"

    def __init__(self, models_dir: str | None = None):
        self.models_dir = models_dir or ENCODER_MODELS_DIR
        self._action_clf = None
        self._category_clf = None
        self._load_errors: dict[str, str] = {}
        self._load_error: str | None = None
        self._load()

    def _load(self) -> None:
        """Load both heads; record every failure instead of silently skipping."""
        try:
            from src.model import EmbedPredictor  # noqa: E402
        except ImportError as exc:
            self._load_error = f"Missing dependency: {exc}"
            print(f"[bert] {self._load_error}")
            return

        for task, default_dir in MODEL_DIRS.items():
            model_dir = os.path.join(self.models_dir, os.path.basename(default_dir))
            if not os.path.isdir(model_dir):
                self._load_errors[task] = f"model dir not found: {model_dir}"
                print(f"[bert] {self._load_errors[task]}")
                continue
            try:
                predictor = EmbedPredictor(model_dir)
                if task == "category":
                    self._category_clf = predictor
                else:
                    self._action_clf = predictor
                print(f"[bert] loaded {task} model from {model_dir}")
            except Exception as exc:  # pragma: no cover - runtime loading
                self._load_errors[task] = str(exc)
                print(f"[bert] failed to load {task} model: {exc}")

        if self._load_errors:
            self._load_error = "; ".join(
                f"{task}: {message}" for task, message in self._load_errors.items()
            )

    @property
    def available(self) -> bool:
        return (
            self._load_error is None
            and self._category_clf is not None
            and self._action_clf is not None
        )

    def load_error(self) -> str | None:
        """Return the load error message, if any."""
        return self._load_error

    @property
    def model_name(self) -> str:
        encoders = []
        for predictor in (self._category_clf, self._action_clf):
            if predictor is not None:
                encoder = predictor.manifest.get("encoder")
                if encoder and encoder not in encoders:
                    encoders.append(encoder)
        return " + ".join(encoders) or "Text encoders"

    def classify(self, email: Email) -> Classification:
        """Predict category and reply nature for one email."""
        if self._load_error:
            raise RuntimeError(
                f"BERT model could not be loaded: {self._load_error}"
            )

        sender = email.sender or ""
        subject = email.subject or ""
        text = _model_text(email)

        if self._category_clf is not None:
            label, _conf = self._category_clf.predict(subject, text, sender)
            category = label if label in CONTENT_CATEGORIES else DEFAULT_CONTENT
        else:
            category = DEFAULT_CONTENT

        if self._action_clf is not None:
            label, _conf = self._action_clf.predict(subject, text, sender)
            action = label if label in REPLY_NATURE else DEFAULT_REPLY
        else:
            action = DEFAULT_REPLY

        return Classification(
            content_category=category,
            reply_nature=action,
            deadline=None,
            reason="bert frozen-encoder head",
        )
