"""BERT-based email classifier for the email-sorter app.

Wraps the frozen-encoder heads trained by ``bert/train.py`` so they drop in
place of (or alongside) the Llama/Ollama classifier.

Usage::

    from app.bert_classifier import BertClassifier

    clf = BertClassifier()
    result = clf.classify(email)  # returns app.models.Classification
"""

from __future__ import annotations

import os
import sys

# bert/ is three levels up from email-sorter/app/bert_classifier.py:
#   bert_classifier.py -> app/ -> email-sorter/ -> dss5105-proj/ -> bert/
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
BERT_DIR = os.path.join(REPO_ROOT, "bert")
if BERT_DIR not in sys.path:
    sys.path.insert(0, BERT_DIR)

from .classifier_base import BaseClassifier
from .models import Classification, Email
from .rules import category_by_rule
from .taxonomy import CONTENT_CATEGORIES, DEFAULT_CONTENT, DEFAULT_REPLY, REPLY_NATURE

BERT_MODELS_DIR = os.path.join(REPO_ROOT, "bert", "models")

# Task -> model dir mapping
MODEL_DIRS = {
    "category": os.path.join(BERT_MODELS_DIR, "category_head"),
    "action": os.path.join(BERT_MODELS_DIR, "action_head"),
}


def _model_text(email: Email) -> str:
    """Return the text the frozen heads were trained on.

    The providers keep a short ``preview`` (first 200 characters) for display
    and a full ``body`` for classification. The offline evaluator and the
    standalone ``EmbedPredictor`` examples use the full body, so prefer it here
    too and fall back to ``preview`` only when the body is empty.
    """
    body = (email.body or "").strip()
    preview = (email.preview or "").strip()
    return body or preview


class BertClassifier(BaseClassifier):
    """Frozen-encoder BERT classifier backend.

    Loads two small logistic-regression heads (category + action) trained in
    bert/train.py. Sender rules (e.g. Canvas -> canva) are applied first, then
    the model predicts the remaining label.
    """

    name = "bert"

    def __init__(self, models_dir: str | None = None):
        self.models_dir = models_dir or BERT_MODELS_DIR
        self._action_clf = None
        self._category_clf = None
        self._load_errors: dict[str, str] = {}
        self._load_error: str | None = None
        self._load()

    def _load(self) -> None:
        """Load both heads; record every failure instead of silently skipping."""
        # Lazy import of EmbedPredictor (requires numpy/torch/transformers)
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

    def classify(self, email: Email) -> Classification:
        """Classify an email and return a ``Classification`` object.

        Sender rules run first (Canvas -> canva). The BERT heads predict the
        other labels. If a head is unavailable at runtime, its label falls back
        to the app default.
        """
        if self._load_error:
            raise RuntimeError(
                f"BERT model could not be loaded: {self._load_error}"
            )

        sender = email.sender or ""
        subject = email.subject or ""
        text = _model_text(email)

        # --- sender rules first ---
        rule_cat = category_by_rule(sender)

        # --- category ---
        if rule_cat:
            category = rule_cat
        elif self._category_clf is not None:
            label, _conf = self._category_clf.predict(subject, text, sender)
            category = label if label in CONTENT_CATEGORIES else DEFAULT_CONTENT
        else:
            category = DEFAULT_CONTENT

        # --- action ---
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
