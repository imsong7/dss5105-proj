"""Classifier wrapper for the saved classical ML pipelines."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from sklearn.naive_bayes import ComplementNB

from .classifier_base import BaseClassifier
from .models import Classification, Email

ML_DIR = Path(__file__).resolve().parents[2] / "classical-ml"
ML_SOURCE_DIR = ML_DIR / "src"
if str(ML_SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(ML_SOURCE_DIR))
ML_MODELS_DIR = ML_DIR / "artifacts"
CATEGORY_LABELS = {
    "fosgeneral": "general",
    "careerenhancement": "career",
    "medicaluhc": "medical",
    "othersoutofnusdomain": "others",
    "promotions": "promotional",
    "canvas": "canva",
}
ACTION_LABELS = {
    "needsareply": "needs_reply",
    "needsanaction": "needs_action",
    "furtherreview": "no_immediate_action",
    "reminder": "reminder",
}


class BalancedComplementNB(ComplementNB):
    """Compatibility class for models serialized by the standalone trainer."""

    def fit(self, X, y, sample_weight=None):
        if sample_weight is None:
            labels = pd.Series(y)
            counts = labels.value_counts()
            weights = len(labels) / (len(counts) * counts)
            sample_weight = labels.map(weights).to_numpy()
        return super().fit(X, y, sample_weight=sample_weight)


def models_ready() -> bool:
    return all(
        (ML_MODELS_DIR / filename).is_file()
        for filename in ("email_category_model.joblib", "required_action_model.joblib")
    )


def _normalise_label(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _load_pipeline(path: Path):
    import joblib

    main_module = sys.modules["__main__"]
    missing = object()
    previous = vars(main_module).get("BalancedComplementNB", missing)
    setattr(main_module, "BalancedComplementNB", BalancedComplementNB)
    try:
        return joblib.load(path)
    finally:
        if previous is missing:
            delattr(main_module, "BalancedComplementNB")
        else:
            setattr(main_module, "BalancedComplementNB", previous)


class MLClassifier(BaseClassifier):
    """Load and apply the production pipelines saved by the ML training script."""

    name = "ml"

    def __init__(self, models_dir: Path | str | None = None):
        directory = Path(models_dir) if models_dir is not None else ML_MODELS_DIR
        category_path = directory / "email_category_model.joblib"
        action_path = directory / "required_action_model.joblib"
        missing = [str(path) for path in (category_path, action_path) if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "Production ML model file(s) not found: "
                + ", ".join(missing)
                + ". Train the models with "
                "PYTHONPATH=classical-ml/src python -m train_email_ml."
            )

        self._category_model = _load_pipeline(category_path)
        self._action_model = _load_pipeline(action_path)

    @property
    def model_name(self) -> str:
        def estimator_name(model) -> str:
            if hasattr(model, "named_steps"):
                model = model.named_steps.get("classifier", model)
            return type(model).__name__

        return (
            f"category: {estimator_name(self._category_model)}; "
            f"action: {estimator_name(self._action_model)}"
        )

    def classify(self, email: Email) -> Classification:
        body = (email.body or "").strip() or (email.preview or "").strip()
        text = f"{email.subject.strip()}\n{body}".strip()
        category_label = str(self._category_model.predict([text])[0])
        action_label = str(self._action_model.predict([text])[0])
        category = CATEGORY_LABELS.get(_normalise_label(category_label))
        action = ACTION_LABELS.get(_normalise_label(action_label))
        if category is None:
            raise ValueError(f"Unsupported ML category label: {category_label!r}")
        if action is None:
            raise ValueError(f"Unsupported ML action label: {action_label!r}")

        return Classification(
            content_category=category,
            reply_nature=action,
            deadline=None,
            reason="Classical ML TF-IDF pipeline.",
        )
