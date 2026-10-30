"""Classifier wrapper for the saved classical ML pipelines."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from sklearn.naive_bayes import ComplementNB

from .backends import BaseClassifier
from .schemas import Classification, Email

ML_DIR = Path(__file__).resolve().parents[2] / "classical-ml"
ML_SOURCE_DIR = ML_DIR / "src"
if str(ML_SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(ML_SOURCE_DIR))
ML_MODELS_DIR = ML_DIR / "artifacts"
TASK_FILES = {
    "category": "email_category_model.joblib",
    "action": "required_action_model.joblib",
}
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


def models_ready(tasks: tuple[str, ...] | list[str] | str = ("category", "action")) -> bool:
    """True when every requested pipeline file exists."""
    if isinstance(tasks, str):
        tasks = (tasks,)
    files = [TASK_FILES[task] for task in tasks if task in TASK_FILES]
    return bool(files) and all((ML_MODELS_DIR / name).is_file() for name in files)


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

    def __init__(
        self,
        models_dir: Path | str | None = None,
        tasks: tuple[str, ...] = ("category", "action"),
    ):
        directory = Path(models_dir) if models_dir is not None else ML_MODELS_DIR
        self.tasks = (tasks,) if isinstance(tasks, str) else tuple(tasks)
        paths = {
            task: directory / TASK_FILES[task]
            for task in self.tasks
            if task in TASK_FILES
        }
        missing = [str(path) for path in paths.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "Production ML model file(s) not found: "
                + ", ".join(missing)
                + ". Train the models with "
                "PYTHONPATH=classical-ml/src python -m train_email_ml."
            )

        self._category_model = (
            _load_pipeline(paths["category"]) if "category" in paths else None
        )
        self._action_model = (
            _load_pipeline(paths["action"]) if "action" in paths else None
        )

    @property
    def model_name(self) -> str:
        def estimator_name(model) -> str:
            if hasattr(model, "named_steps"):
                model = model.named_steps.get("classifier", model)
            return type(model).__name__

        parts = [
            f"{task}: {estimator_name(model)}"
            for task, model in (
                ("category", self._category_model),
                ("action", self._action_model),
            )
            if model is not None
        ]
        return "; ".join(parts) or "Classical ML"

    @staticmethod
    def _text(email: Email) -> str:
        body = (email.body or "").strip() or (email.preview or "").strip()
        return f"{email.subject.strip()}\n{body}".strip()

    def _predict(self, task: str, email: Email) -> str:
        model = getattr(self, f"_{task}_model", None)
        if model is None:
            raise RuntimeError(f"The {task} ML pipeline is not loaded.")
        label = str(model.predict([self._text(email)])[0])
        labels = CATEGORY_LABELS if task == "category" else ACTION_LABELS
        mapped = labels.get(_normalise_label(label))
        if mapped is None:
            raise ValueError(f"Unsupported ML {task} label: {label!r}")
        return mapped

    def predict_category(self, email: Email) -> str:
        return self._predict("category", email)

    def predict_action(self, email: Email) -> str:
        return self._predict("action", email)

    def classify(self, email: Email) -> Classification:
        return Classification(
            content_category=self.predict_category(email),
            reply_nature=self.predict_action(email),
            deadline=None,
            reason="Classical ML TF-IDF pipeline.",
        )
