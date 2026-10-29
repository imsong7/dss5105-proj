"""Train classical ML baselines for the DSS5105 email project.

Expected workbook structure
---------------------------
One Excel workbook contains multiple worksheets.  Each worksheet contains
emails belonging to one label, and its name contains both a team-member name
and one of the labels below, for example:

    Amelia - FoS General
    Gouri_Needs a reply
    Ssy Promotions

Required email columns (case-insensitive):
    Subject
    Preview OR Body

Useful optional columns:
    Internet Message ID
    From

The script builds two independent classifiers:
    1. email_category: FoS General, Career Enhancement, Medical (UHC),
       Others/Out of NUS domain, Promotions
    2. required_action: Needs a reply, Needs an action, Further review,
       Reminder

Canvas is handled by the sender/rule shown in the team's architecture, so it
is collected and reported but excluded from the category ML model.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC


# ---------------------------------------------------------------------------
# SETTINGS: change only EXCEL_FILE if your workbook has a different filename.
# ML_LABELS_XLSX overrides the workbook path without editing this file.
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
EXCEL_FILE = Path(os.environ.get("ML_LABELS_XLSX", BASE_DIR / "labels.xlsx"))
# Shared review CSV: the same reviewed emails, used when the workbook is absent.
LABELS_CSV = Path(
    os.environ.get("ML_LABELS_CSV", BASE_DIR.parent.parent / "data" / "labels.csv")
)
SYNTHETIC_ACTION_FILE = BASE_DIR.parent.parent / "data" / "synthetic.csv"
OUTPUT_DIR = BASE_DIR.parent / "artifacts"
REPORTS_DIR = BASE_DIR.parent / "reports"
RANDOM_STATE = 42
TEST_SIZE = 0.20

DEFAULT_TFIDF_OPTIONS = {
    "ngram_range": (1, 2),
    "min_df": 1,
    "max_df": 0.98,
    "sublinear_tf": True,
    "max_features": 30000,
    "strip_accents": "unicode",
}

# Best configurations from repeated training-split CV (`experiments tune`).
TASK_TFIDF_OPTIONS = {
    "email_category": {
        "ngram_range": (1, 2),
        "min_df": 2,
        "max_df": 0.90,
        "sublinear_tf": False,
        "max_features": 30000,
        "strip_accents": "unicode",
    },
    "required_action": {
        "ngram_range": (1, 2),
        "min_df": 1,
        "max_df": 0.90,
        "sublinear_tf": True,
        "max_features": 30000,
        "strip_accents": "unicode",
    },
}

TASK_MODEL_PARAMS = {
    "email_category": {
        "logistic_regression": {},
        "linear_svm": {"C": 10.0},
        "complement_nb_balanced": {"alpha": 0.1},
    },
    "required_action": {
        "logistic_regression": {},
        "linear_svm": {},
        "complement_nb_balanced": {"alpha": 3.0},
    },
}


# The script ignores spaces, punctuation and capitalisation in sheet names.
# Add another alias here only if your team uses a different spelling.
CATEGORY_ALIASES = {
    "fosgeneral": "FoS General",
    "fos": "FoS General",
    "careerenhancement": "Career Enhancement",
    "career": "Career Enhancement",
    "medicaluhc": "Medical (UHC)",
    "uhcmedical": "Medical (UHC)",
    "medical": "Medical (UHC)",
    "othersoutofnusdomain": "Others/Out of NUS domain",
    "othersoutofdomain": "Others/Out of NUS domain",
    "outofnusdomain": "Others/Out of NUS domain",
    "externalemails": "Others/Out of NUS domain",
    "external": "Others/Out of NUS domain",
    "others": "Others/Out of NUS domain",
    "promotions": "Promotions",
    "promotion": "Promotions",
    "canvas": "Canvas",
}

ACTION_ALIASES = {
    "needsareply": "Needs a reply",
    "needsreply": "Needs a reply",
    "needareply": "Needs a reply",
    "needreply": "Needs a reply",
    "needsanaction": "Needs an action",
    "needsaction": "Needs an action",
    "needanaction": "Needs an action",
    "needaction": "Needs an action",
    "furtherreview": "Further review",
    "review": "Further review",
    # Backwards compatibility for worksheets created before the team renamed
    # the old Ignore class to Further review.
    "ignore": "Further review",
    "reminder": "Reminder",
}

COLUMN_ALIASES = {
    "subject": ["subject"],
    "text": ["preview", "body", "emailbody", "content", "bodypreview"],
    "message_id": [
        "reviewid", "internetmessageid", "messageid", "emailid", "id"
    ],
    "sender": ["from", "sender", "fromaddress"],
}

# Final values used in the new one-sheet labelled workbook.
CATEGORY_VALUE_MAP = {
    "general": "FoS General",
    "fosgeneral": "FoS General",
    "career": "Career Enhancement",
    "careerenhancement": "Career Enhancement",
    "medical": "Medical (UHC)",
    "medicaluhc": "Medical (UHC)",
    "others": "Others/Out of NUS domain",
    "othersoutofnusdomain": "Others/Out of NUS domain",
    "promotional": "Promotions",
    "promotions": "Promotions",
    "canvas": "Canvas",
    "canva": "Canvas",  # Current workbook spelling; standardise later.
    "skip": "__skip__",
}

ACTION_VALUE_MAP = {
    "needsreply": "Needs a reply",
    "needsareply": "Needs a reply",
    "needsaction": "Needs an action",
    "needsanaction": "Needs an action",
    # This follows the team's latest presentation label. If the team decides
    # these concepts differ, relabel the workbook instead of changing silently.
    "noimmediateaction": "Further review",
    "furtherreview": "Further review",
    "reminder": "Reminder",
    "skip": "__skip__",
}


class BalancedComplementNB(ComplementNB):
    """ComplementNB with inverse-frequency sample weights."""

    def fit(self, X, y, sample_weight=None):
        if sample_weight is None:
            labels = pd.Series(y)
            counts = labels.value_counts()
            weight_map = len(labels) / (len(counts) * counts)
            sample_weight = labels.map(weight_map).to_numpy()
        return super().fit(X, y, sample_weight=sample_weight)


def normalise(value: object) -> str:
    """Lowercase text and remove punctuation/spaces for reliable matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def find_column(frame: pd.DataFrame, aliases: list[str]) -> str | None:
    normalised_columns = {normalise(column): column for column in frame.columns}
    for alias in aliases:
        if normalise(alias) in normalised_columns:
            return normalised_columns[normalise(alias)]
    return None


def label_from_sheet(sheet_name: str) -> tuple[str | None, str | None]:
    """Return (task, label) inferred from a worksheet name."""
    cleaned = normalise(sheet_name)

    # A worksheet such as "career+external emails" contains two category
    # labels.  Without a label column for every row, assigning one label to
    # the whole sheet would silently corrupt the training data.
    if "career" in cleaned and "external" in cleaned:
        return "ambiguous", None

    # Longest aliases first prevents a short alias matching too early.
    for alias in sorted(ACTION_ALIASES, key=len, reverse=True):
        if alias in cleaned:
            return "required_action", ACTION_ALIASES[alias]

    for alias in sorted(CATEGORY_ALIASES, key=len, reverse=True):
        if alias in cleaned:
            return "email_category", CATEGORY_ALIASES[alias]

    return None, None


def _labels_to_frames(
    frame: pd.DataFrame,
    source_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the ML frames from a table with row-level category and action."""
    frame = frame.dropna(how="all").copy()
    if frame.empty:
        raise ValueError(f"{source_name} has no rows.")

    subject_column = find_column(frame, COLUMN_ALIASES["subject"])
    text_column = find_column(frame, COLUMN_ALIASES["text"])
    message_id_column = find_column(frame, COLUMN_ALIASES["message_id"])
    sender_column = find_column(frame, COLUMN_ALIASES["sender"])
    category_column = find_column(frame, ["category"])
    action_column = find_column(frame, ["action"])
    source_column = find_column(frame, ["source_sheets", "source_sheet"])

    missing = []
    if subject_column is None and text_column is None:
        missing.append("Subject or Preview/Body")
    if category_column is None:
        missing.append("category")
    if action_column is None:
        missing.append("action")
    if missing:
        raise ValueError(
            "The labels worksheet is missing required columns: " + ", ".join(missing)
        )

    base = pd.DataFrame(index=frame.index)
    base["subject"] = (
        frame[subject_column].fillna("").astype(str) if subject_column else ""
    )
    base["body"] = frame[text_column].fillna("").astype(str) if text_column else ""
    base["message_id"] = (
        frame[message_id_column].fillna("").astype(str)
        if message_id_column
        else ""
    )
    base["sender"] = (
        frame[sender_column].fillna("").astype(str) if sender_column else ""
    )
    base["source_sheet"] = (
        frame[source_column].fillna(source_name).astype(str)
        if source_column
        else source_name
    )
    base["text"] = (
        base["subject"].str.strip() + "\n" + base["body"].str.strip()
    ).str.strip()
    base = base[base["text"].str.len() > 0].copy()

    raw_category = frame.loc[base.index, category_column].map(normalise)
    raw_action = frame.loc[base.index, action_column].map(normalise)
    mapped_category = raw_category.map(CATEGORY_VALUE_MAP)
    mapped_action = raw_action.map(ACTION_VALUE_MAP)

    unknown_categories = sorted(
        frame.loc[base.index[mapped_category.isna()], category_column]
        .dropna()
        .astype(str)
        .unique()
    )
    unknown_actions = sorted(
        frame.loc[base.index[mapped_action.isna()], action_column]
        .dropna()
        .astype(str)
        .unique()
    )
    if unknown_categories or unknown_actions:
        details = []
        if unknown_categories:
            details.append(f"unknown category values: {unknown_categories}")
        if unknown_actions:
            details.append(f"unknown action values: {unknown_actions}")
        raise ValueError("; ".join(details))

    category_data = base.copy()
    category_data["label"] = mapped_category
    canvas_data = category_data[category_data["label"] == "Canvas"].copy()
    category_data = category_data[
        ~category_data["label"].isin(["Canvas", "__skip__"])
    ].copy()

    action_data = base.copy()
    action_data["label"] = mapped_action
    action_data = action_data[action_data["label"] != "__skip__"].copy()

    print(f"Loaded unified labels sheet: {source_name}")
    print(f"  Category ML rows: {len(category_data)}")
    print(f"  Action ML rows:   {len(action_data)}")
    print(f"  Canvas rule rows: {len(canvas_data)}")
    return category_data, action_data, canvas_data


def read_unified_labels_sheet(sheet_name: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the new format where each row has final category/action labels."""
    frame = pd.read_excel(EXCEL_FILE, sheet_name=sheet_name)
    return _labels_to_frames(frame, sheet_name)


def read_labeled_csv(path: Path | str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the shared review CSV (data/labels.csv) in the same shape.

    This is the fallback when the labelled Excel workbook is not on this
    machine: the CSV holds the same reviewed emails with their labels.
    """
    csv_path = Path(path or LABELS_CSV)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Cannot find {csv_path.name}: {csv_path}\n"
            "Set ML_LABELS_CSV to the labelled CSV, or ML_LABELS_XLSX to the workbook."
        )
    frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return _labels_to_frames(frame, csv_path.name)


def read_workbook() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not EXCEL_FILE.exists():
        # The workbook is real email data and is not committed; the shared
        # review CSV carries the same reviewed rows.
        print(
            f"{EXCEL_FILE.name} not found in {EXCEL_FILE.parent}; "
            f"using the shared review CSV {LABELS_CSV.name} instead."
        )
        return read_labeled_csv()

    workbook = pd.ExcelFile(EXCEL_FILE)

    # Prefer the new format: one worksheet with row-level category/action.
    for sheet_name in workbook.sheet_names:
        if normalise(sheet_name) == "labels":
            return read_unified_labels_sheet(sheet_name)

    # Backwards-compatible fallback for the older one-label-per-sheet format.
    collected: dict[str, list[pd.DataFrame]] = {
        "email_category": [],
        "required_action": [],
    }
    canvas_frames: list[pd.DataFrame] = []
    skipped_sheets: list[str] = []

    for sheet_name in workbook.sheet_names:
        task, label = label_from_sheet(sheet_name)
        if task == "ambiguous":
            print(
                f"Skipping mixed-label sheet '{sheet_name}'. Split it into "
                "separate Career Enhancement and Others/Out of NUS domain "
                "worksheets before training."
            )
            continue
        if task is None:
            skipped_sheets.append(sheet_name)
            continue

        frame = pd.read_excel(EXCEL_FILE, sheet_name=sheet_name)
        frame = frame.dropna(how="all").copy()
        if frame.empty:
            print(f"Skipping empty sheet: {sheet_name}")
            continue

        subject_column = find_column(frame, COLUMN_ALIASES["subject"])
        text_column = find_column(frame, COLUMN_ALIASES["text"])
        message_id_column = find_column(frame, COLUMN_ALIASES["message_id"])
        sender_column = find_column(frame, COLUMN_ALIASES["sender"])

        if subject_column is None and text_column is None:
            print(
                f"Skipping '{sheet_name}': no Subject, Preview or Body column found."
            )
            continue

        output = pd.DataFrame(index=frame.index)
        output["subject"] = (
            frame[subject_column].fillna("").astype(str)
            if subject_column
            else ""
        )
        output["body"] = (
            frame[text_column].fillna("").astype(str)
            if text_column
            else ""
        )
        output["message_id"] = (
            frame[message_id_column].fillna("").astype(str)
            if message_id_column
            else ""
        )
        output["sender"] = (
            frame[sender_column].fillna("").astype(str)
            if sender_column
            else ""
        )
        output["source_sheet"] = sheet_name
        output["label"] = label
        output["text"] = (
            output["subject"].str.strip()
            + "\n"
            + output["body"].str.strip()
        ).str.strip()
        output = output[output["text"].str.len() > 0]

        print(f"Loaded {len(output):4d} rows | {label:28s} | {sheet_name}")

        if label == "Canvas":
            canvas_frames.append(output)
        else:
            collected[task].append(output)

    if skipped_sheets:
        print("\nSheets not recognised and skipped:")
        for name in skipped_sheets:
            print(f"  - {name}")

    def combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame(
                columns=[
                    "subject", "body", "message_id", "sender",
                    "source_sheet", "label", "text",
                ]
            )
        return pd.concat(frames, ignore_index=True)

    return (
        combine(collected["email_category"]),
        combine(collected["required_action"]),
        combine(canvas_frames),
    )


def load_synthetic_action_data() -> pd.DataFrame:
    """Load synthetic required_action rows, if the separate file exists."""
    empty = pd.DataFrame(
        columns=[
            "subject", "body", "message_id", "sender",
            "source_sheet", "label", "text", "source",
        ]
    )
    if not SYNTHETIC_ACTION_FILE.exists():
        print(
            f"\nNo synthetic action file found ({SYNTHETIC_ACTION_FILE.name}); "
            "training on real data only."
        )
        return empty

    frame = pd.read_csv(SYNTHETIC_ACTION_FILE)
    frame = frame.dropna(how="all").copy()

    subject_column = find_column(frame, COLUMN_ALIASES["subject"])
    text_column = find_column(frame, COLUMN_ALIASES["text"])
    message_id_column = find_column(frame, COLUMN_ALIASES["message_id"])
    sender_column = find_column(frame, COLUMN_ALIASES["sender"])
    action_column = find_column(frame, ["action"])
    source_sheet_column = find_column(frame, ["source_sheet", "source_sheets"])
    source_column = find_column(frame, ["source"])

    if subject_column is None and text_column is None:
        raise ValueError(
            f"{SYNTHETIC_ACTION_FILE.name} needs a Subject or Body column."
        )
    if action_column is None:
        raise ValueError(f"{SYNTHETIC_ACTION_FILE.name} needs an action column.")

    base = pd.DataFrame(index=frame.index)
    base["subject"] = (
        frame[subject_column].fillna("").astype(str) if subject_column else ""
    )
    base["body"] = frame[text_column].fillna("").astype(str) if text_column else ""
    base["message_id"] = (
        frame[message_id_column].fillna("").astype(str)
        if message_id_column
        else ""
    )
    base["sender"] = (
        frame[sender_column].fillna("").astype(str) if sender_column else ""
    )
    base["source_sheet"] = (
        frame[source_sheet_column].fillna("synthetic").astype(str)
        if source_sheet_column
        else "synthetic"
    )
    base["source"] = (
        frame[source_column].fillna("synthetic").astype(str)
        if source_column
        else "synthetic"
    )
    base["text"] = (
        base["subject"].str.strip() + "\n" + base["body"].str.strip()
    ).str.strip()
    base = base[base["text"].str.len() > 0].copy()

    raw_action = frame.loc[base.index, action_column].map(normalise)
    mapped_action = raw_action.map(ACTION_VALUE_MAP)
    unknown_actions = sorted(
        frame.loc[base.index[mapped_action.isna()], action_column]
        .dropna()
        .astype(str)
        .unique()
    )
    if unknown_actions:
        raise ValueError(
            f"{SYNTHETIC_ACTION_FILE.name} has unknown action values: "
            f"{unknown_actions}"
        )

    base["label"] = mapped_action
    base = base[~base["label"].isin(["__skip__", "Canvas"])].copy()

    print(f"Loaded synthetic action sheet: {SYNTHETIC_ACTION_FILE.name}")
    print(f"  Synthetic rows: {len(base)}")
    if not base.empty:
        print(base["label"].value_counts().to_string())
    return base


def remove_duplicates_and_check_conflicts(
    data: pd.DataFrame,
    task_name: str,
) -> pd.DataFrame:
    data = data.copy()
    data["dedupe_key"] = data["message_id"].str.strip()
    missing_id = data["dedupe_key"].eq("")
    data.loc[missing_id, "dedupe_key"] = (
        data.loc[missing_id, "subject"].map(normalise)
        + "::"
        + data.loc[missing_id, "body"].map(normalise)
    )

    # Detect repeated content even when the review_id/message_id differs.  For
    # rows with an empty body, fall back to the message-level key so unrelated
    # empty-body emails are not collapsed together.
    data["content_key"] = (
        data["subject"].map(normalise) + "::" + data["body"].map(normalise)
    )
    empty_body = data["body"].fillna("").map(normalise).eq("")
    data.loc[empty_body, "content_key"] = data.loc[empty_body, "dedupe_key"]

    for key, suffix in (
        ("content_key", "content"),
        ("dedupe_key", "message"),
    ):
        conflicts = (
            data.groupby(key)["label"]
            .nunique()
            .loc[lambda counts: counts > 1]
        )
        if not conflicts.empty:
            conflict_rows = data[data[key].isin(conflicts.index)][
                ["subject", "label", "source_sheet", "message_id"]
            ].sort_values("subject")
            conflict_file = OUTPUT_DIR / f"{task_name}_{suffix}_label_conflicts.csv"
            conflict_rows.to_csv(
                conflict_file, index=False, encoding="utf-8-sig"
            )
            raise ValueError(
                f"{task_name}: the same email content has different labels. "
                f"Review {conflict_file.name}."
            )

    before = len(data)
    data = data.drop_duplicates("content_key", keep="first")
    after_content = len(data)
    data = data.drop_duplicates("dedupe_key", keep="first").reset_index(drop=True)
    removed_content = before - after_content
    removed_message = after_content - len(data)
    print(
        f"{task_name}: removed {before - len(data)} duplicate rows "
        f"({removed_content} repeated content, {removed_message} same message)."
    )
    return data.drop(columns=["content_key"])


def build_models(task_name: str | None = None) -> dict[str, Pipeline]:
    tfidf_options = TASK_TFIDF_OPTIONS.get(task_name, DEFAULT_TFIDF_OPTIONS)
    model_params = TASK_MODEL_PARAMS.get(task_name, {})

    return {
        "logistic_regression": Pipeline(
            [
                ("tfidf", TfidfVectorizer(**tfidf_options)),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=2000,
                        class_weight="balanced",
                        random_state=RANDOM_STATE,
                        **model_params.get("logistic_regression", {}),
                    ),
                ),
            ]
        ),
        "linear_svm": Pipeline(
            [
                ("tfidf", TfidfVectorizer(**tfidf_options)),
                (
                    "classifier",
                    LinearSVC(
                        class_weight="balanced",
                        random_state=RANDOM_STATE,
                        **model_params.get("linear_svm", {}),
                    ),
                ),
            ]
        ),
        "complement_nb_balanced": Pipeline(
            [
                ("tfidf", TfidfVectorizer(**tfidf_options)),
                (
                    "classifier",
                    BalancedComplementNB(
                        **model_params.get("complement_nb_balanced", {})
                    ),
                ),
            ]
        ),
    }


def evaluate_real_cv_with_synthetic(
    data: pd.DataFrame,
    synthetic_data: pd.DataFrame,
    task_name: str,
    n_splits: int = 5,
    n_repeats: int = 5,
) -> dict[str, dict[str, float | int]]:
    """Cross-validate on real emails, adding synthetic rows only to train folds.

    ``n_repeats`` controls repeated stratified CV.  The returned mean/std are
    computed across repeat-level means, so repeated runs do not pretend that
    correlated folds are independent samples.
    """
    counts = data["label"].value_counts()
    folds = min(n_splits, int(counts.min()))
    if folds < 2:
        return {}

    models = build_models(task_name)
    scores: dict[str, list[float]] = {name: [] for name in models}
    has_synthetic = synthetic_data is not None and not synthetic_data.empty

    for repeat in range(n_repeats):
        cv = StratifiedKFold(
            n_splits=folds,
            shuffle=True,
            random_state=RANDOM_STATE + repeat,
        )
        repeat_scores: dict[str, list[float]] = {name: [] for name in models}

        for train_index, validation_index in cv.split(
            data["text"], data["label"]
        ):
            real_train = data.iloc[train_index]
            real_validation = data.iloc[validation_index]

            if has_synthetic:
                validation_keys = set(real_validation["text"].map(normalise))
                extra_train = synthetic_data[
                    ~synthetic_data["text"].map(normalise).isin(
                        validation_keys
                    )
                ].copy()
                extra_train = extra_train.reindex(columns=real_train.columns)
                train_text = pd.concat(
                    [real_train["text"], extra_train["text"]],
                    ignore_index=True,
                )
                train_label = pd.concat(
                    [real_train["label"], extra_train["label"]],
                    ignore_index=True,
                )
            else:
                train_text = real_train["text"]
                train_label = real_train["label"]

            for model_name, model in models.items():
                model.fit(train_text, train_label)
                predictions = model.predict(real_validation["text"])
                repeat_scores[model_name].append(
                    float(
                        f1_score(
                            real_validation["label"],
                            predictions,
                            average="macro",
                            zero_division=0,
                        )
                    )
                )

        for model_name in models:
            scores[model_name].append(
                float(pd.Series(repeat_scores[model_name]).mean())
            )

    def spread(values: list[float]) -> float:
        return float(pd.Series(values).std()) if len(values) > 1 else 0.0

    return {
        name: {
            "mean": float(pd.Series(repeat_means).mean()),
            "std": spread(repeat_means),
            "folds": folds,
            "repeats": n_repeats,
        }
        for name, repeat_means in scores.items()
    }


def save_confusion_matrix(
    true_labels: pd.Series,
    predicted_labels: pd.Series,
    labels: list[str],
    task_name: str,
) -> None:
    matrix = confusion_matrix(true_labels, predicted_labels, labels=labels)
    matrix_frame = pd.DataFrame(matrix, index=labels, columns=labels)
    matrix_frame.to_csv(
        OUTPUT_DIR / f"{task_name}_confusion_matrix.csv",
        encoding="utf-8-sig",
    )

    plt.figure(figsize=(max(7, len(labels) * 1.5), max(5, len(labels) * 1.1)))
    sns.heatmap(matrix_frame, annot=True, fmt="d", cmap="Blues")
    plt.title(f"{task_name.replace('_', ' ').title()} Confusion Matrix")
    plt.xlabel("Predicted label")
    plt.ylabel("True label")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / f"{task_name}_confusion_matrix.png", dpi=200)
    plt.close()


def train_task(
    data: pd.DataFrame,
    task_name: str,
    synthetic_train: pd.DataFrame | None = None,
) -> dict[str, object]:
    print(f"\n{'=' * 70}\nTraining task: {task_name}\n{'=' * 70}")
    data = remove_duplicates_and_check_conflicts(data, task_name)

    counts = data["label"].value_counts()
    print("\nClass counts:")
    print(counts.to_string())

    if len(counts) < 2:
        raise ValueError(f"{task_name} needs at least two different labels.")
    if counts.min() < 2:
        raise ValueError(
            f"{task_name}: every label needs at least 2 emails. Current minimum is "
            f"{counts.min()}."
        )

    number_of_classes = len(counts)
    test_count = max(number_of_classes, math.ceil(len(data) * TEST_SIZE))
    if len(data) - test_count < number_of_classes:
        raise ValueError(
            f"{task_name}: there are too few emails for a stratified train/test "
            "split. Add more examples to each label."
        )

    train_data, test_data = train_test_split(
        data,
        test_size=test_count,
        random_state=RANDOM_STATE,
        stratify=data["label"],
    )
    real_train_data = train_data.copy()
    synthetic_used = pd.DataFrame()

    if synthetic_train is not None and not synthetic_train.empty:
        synthetic_used = synthetic_train.copy()

        # Never let a synthetic row duplicate a real row.  This also guarantees
        # that no test email can leak into training.
        real_text_keys = set(data["text"].map(normalise))
        synthetic_used = synthetic_used[
            ~synthetic_used["text"].map(normalise).isin(real_text_keys)
        ].copy()
        synthetic_used["dedupe_key"] = synthetic_used["text"].map(normalise)
        synthetic_used = synthetic_used.drop_duplicates("dedupe_key").reset_index(
            drop=True
        )

        allowed_labels = set(data["label"].unique())
        synthetic_used = synthetic_used[
            synthetic_used["label"].isin(allowed_labels)
        ].copy()

        if synthetic_used.empty:
            print(
                "\nSynthetic rows were empty after overlap filtering; "
                "training on real data only."
            )
        else:
            print(f"\nSynthetic training rows: {len(synthetic_used)} (train only)")
            print(synthetic_used["label"].value_counts().to_string())
            synthetic_used = synthetic_used.reindex(columns=real_train_data.columns)

    if synthetic_used.empty:
        train_data = real_train_data
    else:
        train_data = pd.concat([real_train_data, synthetic_used], ignore_index=True)
        print("\nCombined training class counts:")
        print(train_data["label"].value_counts().to_string())

    # Cross-validation and model selection use real training emails only, so
    # neither the holdout test set nor synthetic rows inflate the selection
    # score.  Repeated CV keeps the choice stable on this small dataset.
    models = build_models(task_name)
    real_cv_with_synthetic = evaluate_real_cv_with_synthetic(
        real_train_data,
        synthetic_used,
        task_name,
    )

    if real_cv_with_synthetic:
        print("\nReal-email repeated CV (synthetic rows in training folds only):")
        for model_name, stats in real_cv_with_synthetic.items():
            print(
                f"  CV Macro-F1 | {model_name:20s}: "
                f"{stats['mean']:.3f} (+/- {stats['std']:.3f})"
            )
        best_model_name = max(
            real_cv_with_synthetic,
            key=lambda name: real_cv_with_synthetic[name]["mean"],
        )
        print(f"Selected model by real-email CV: {best_model_name}")
    else:
        best_model_name = "logistic_regression"
        print(
            "Not enough training examples for cross-validation; "
            "using Logistic Regression."
        )

    cv_results = (
        {
            name: float(stats["mean"])
            for name, stats in real_cv_with_synthetic.items()
        }
        if real_cv_with_synthetic
        else {name: None for name in models}
    )

    best_model = models[best_model_name]
    best_model.fit(train_data["text"], train_data["label"])
    predictions = best_model.predict(test_data["text"])

    labels = sorted(data["label"].unique())
    accuracy = float(accuracy_score(test_data["label"], predictions))
    macro_f1 = float(f1_score(test_data["label"], predictions, average="macro"))
    report_dictionary = classification_report(
        test_data["label"],
        predictions,
        labels=labels,
        output_dict=True,
        zero_division=0,
    )
    report_text = classification_report(
        test_data["label"],
        predictions,
        labels=labels,
        zero_division=0,
    )

    print(f"\nSelected model: {best_model_name}")
    print(f"Test accuracy: {accuracy:.3f}")
    print(f"Test Macro-F1: {macro_f1:.3f}\n")
    print(report_text)

    test_output = test_data[
        ["subject", "body", "message_id", "source_sheet", "label"]
    ].copy()
    test_output["predicted_label"] = predictions
    test_output["correct"] = test_output["label"] == test_output["predicted_label"]
    test_output.to_csv(
        OUTPUT_DIR / f"{task_name}_test_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    split_output = data[
        ["subject", "message_id", "source_sheet", "label", "dedupe_key"]
    ].copy()
    split_output["split"] = "train"
    split_output.loc[test_data.index, "split"] = "test"
    split_output["source"] = "real"
    if not synthetic_used.empty:
        synthetic_split = synthetic_used[
            ["subject", "message_id", "source_sheet", "label", "dedupe_key"]
        ].copy()
        synthetic_split["split"] = "train_synthetic"
        synthetic_split["source"] = "synthetic"
        split_output = pd.concat([split_output, synthetic_split], ignore_index=True)
    split_output.to_csv(
        OUTPUT_DIR / f"{task_name}_data_split.csv",
        index=False,
        encoding="utf-8-sig",
    )

    save_confusion_matrix(
        test_data["label"],
        pd.Series(predictions, index=test_data.index),
        labels,
        task_name,
    )

    # Refit the selected model on every available real email plus any synthetic
    # training rows for deployment.
    final_model = build_models(task_name)[best_model_name]
    if synthetic_used.empty:
        final_text = data["text"]
        final_labels = data["label"]
    else:
        final_text = pd.concat(
            [data["text"], synthetic_used["text"]], ignore_index=True
        )
        final_labels = pd.concat(
            [data["label"], synthetic_used["label"]], ignore_index=True
        )
    final_model.fit(final_text, final_labels)
    joblib.dump(final_model, OUTPUT_DIR / f"{task_name}_model.joblib")

    metrics = {
        "task": task_name,
        "selected_model": best_model_name,
        "random_state": RANDOM_STATE,
        "total_emails": int(len(data)),
        "train_emails": int(len(real_train_data)),
        "real_train_emails": int(len(real_train_data)),
        "synthetic_train_emails": int(len(synthetic_used)),
        "combined_train_emails": int(len(train_data)),
        "test_emails": int(len(test_data)),
        "test_is_real_only": True,
        "class_counts": {key: int(value) for key, value in counts.items()},
        "synthetic_class_counts": (
            {
                key: int(value)
                for key, value in synthetic_used["label"].value_counts().items()
            }
            if not synthetic_used.empty
            else {}
        ),
        "combined_train_class_counts": {
            key: int(value)
            for key, value in train_data["label"].value_counts().items()
        },
        "cross_validation_macro_f1": cv_results,
        "cross_validation_is_real_only": True,
        "real_cv_with_synthetic_macro_f1": real_cv_with_synthetic,
        "test_accuracy": accuracy,
        "test_macro_f1": macro_f1,
        "classification_report": report_dictionary,
    }
    with (OUTPUT_DIR / f"{task_name}_metrics.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2)

    return metrics


def print_saved_model_comparison() -> None:
    """Print the latest `experiments compare` table, if it has been generated."""
    comparison_file = OUTPUT_DIR / "model_comparison.csv"
    required_columns = {
        "task",
        "model",
        "cv_macro_f1_mean",
        "cv_macro_f1_std",
        "cv_accuracy_mean",
        "cv_accuracy_std",
    }
    if not comparison_file.exists():
        print(
            "\nTip: run `PYTHONPATH=src python -m experiments compare` to print "
            "the full model comparison table."
        )
        return

    comparison = pd.read_csv(comparison_file)
    if not required_columns.issubset(comparison.columns):
        return

    comparison = comparison.sort_values(
        ["task", "cv_macro_f1_mean"],
        ascending=[True, False],
    )
    display = pd.DataFrame(
        {
            "Task": comparison["task"],
            "Model": comparison["model"],
            "CV Macro-F1": comparison.apply(
                lambda row: (
                    f"{row['cv_macro_f1_mean']:.3f} "
                    f"± {row['cv_macro_f1_std']:.3f}"
                ),
                axis=1,
            ),
            "CV Acc": comparison.apply(
                lambda row: (
                    f"{row['cv_accuracy_mean']:.3f} "
                    f"± {row['cv_accuracy_std']:.3f}"
                ),
                axis=1,
            ),
        }
    )
    print("\n" + "=" * 80)
    print("MODEL COMPARISON (from model_comparison.csv; CV is primary)")
    print("=" * 80)
    print(display.to_string(index=False))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    category_data, action_data, canvas_data = read_workbook()
    if not canvas_data.empty:
        canvas_data.to_csv(
            OUTPUT_DIR / "canvas_rule_emails.csv",
            index=False,
            encoding="utf-8-sig",
        )
        print(
            f"\nCanvas: {len(canvas_data)} rows saved separately for the sender rule."
        )

    synthetic_action = load_synthetic_action_data()

    summary: dict[str, object] = {}
    for task_name, task_data in [
        ("email_category", category_data),
        ("required_action", action_data),
    ]:
        if task_data.empty:
            print(f"\nNo recognised worksheets for {task_name}; task skipped.")
            continue
        extra_train = synthetic_action if task_name == "required_action" else None
        summary[task_name] = train_task(
            task_data,
            task_name,
            synthetic_train=extra_train,
        )

    if not summary:
        raise ValueError(
            "No training data was found. Check the worksheet names and column names."
        )

    with (OUTPUT_DIR / "training_summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print(f"\nFinished. Results were saved to:\n{OUTPUT_DIR}")
    print_saved_model_comparison()


if __name__ == "__main__":
    main()
