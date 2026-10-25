"""Load, validate, split, and synthesize BERT email data."""

import hashlib
import importlib.util
import os
from email.utils import parseaddr

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
TAXONOMY_PATH = os.path.join(REPO_DIR, "email-sorter", "app", "taxonomy.py")

SEED = 42
MAX_LEN = 256
STRIP_SENDER = True
BATCH_SIZE = 16
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01
HEAD_C = 10.0  # inverse L2 strength of the logistic-regression head

TASKS = {"category": "CONTENT_CATEGORIES", "action": "REPLY_NATURE"}

SENDER_RULES = {"category": {"notifications@instructure.com": "canva"}}

# name -> (HF model id, text prefix, pooling)
ENCODERS = {
    "bge-small-en": ("BAAI/bge-small-en-v1.5", "", "cls"),
    "e5-small-multi": ("intfloat/multilingual-e5-small", "query: ", "mean"),
    "distilbert-mean": ("distilbert-base-uncased", "", "mean"),
}
DEFAULT_ENCODERS = {"category": "bge-small-en", "action": "e5-small-multi"}

SKIP = "__skip__"
NEAR_DUP_SIM = 0.8  # Drop synthetic rows this close to a real email (TF-IDF cosine).


# --- Text helpers ---
def _s(v):
    return "" if pd.isna(v) else str(v).strip()


def build_text(subject, from_addr, preview, strip_sender=STRIP_SENDER):
    if strip_sender:
        return f"Subject: {_s(subject)}\n{_s(preview)}"
    return f"From: {_s(from_addr)}\nSubject: {_s(subject)}\n{_s(preview)}"


def sender_address(from_field):
    return parseaddr(_s(from_field))[1].strip().lower()


def sender_rule_label(from_field, task):
    return SENDER_RULES.get(task, {}).get(sender_address(from_field))


# --- Taxonomy ---
class DataError(Exception):
    pass


def load_taxonomy(path=TAXONOMY_PATH):
    """Load label taxonomy from email-sorter/app/taxonomy.py."""
    spec = importlib.util.spec_from_file_location("app_taxonomy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    labels = {task: list(getattr(mod, attr).keys()) for task, attr in TASKS.items()}
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:16]
    return labels, digest


# --- Review CSV -> validated task datasets ---
def task_dataset(review, task, labels, allow_missing=False):
    vals = review[task].fillna("").astype(object).map(_s)
    blank = int((vals == "").sum())
    if blank:
        raise DataError(f"[{task}] {blank} rows not reviewed. Fill an app key or {SKIP}.")
    bad = sorted(set(vals) - set(labels) - {SKIP})
    if bad:
        raise DataError(f"[{task}] unknown labels {bad}; allowed: {labels} or {SKIP}.")
    df = review.assign(label_key=vals)
    rule = df["From"].map(lambda f: sender_rule_label(f, task))
    rule_labels = sorted(set(SENDER_RULES.get(task, {}).values()))
    ruled = df[rule.notna()]
    disagree = ruled[(ruled["label_key"] != rule[rule.notna()]) & (ruled["label_key"] != SKIP)]
    if len(disagree):
        print(f"[warn][{task}] {len(disagree)} rule-matched rows have a different review label; "
              f"the rule wins in the app: {disagree[['review_id', 'label_key']].values.tolist()[:5]}")
    df = df[rule.isna()]
    leaked = df[df["label_key"].isin(rule_labels)]
    if len(leaked):
        raise DataError(f"[{task}] {len(leaked)} rows labelled {rule_labels} but not matched by the sender rule.")
    df = df[df["label_key"] != SKIP].copy()
    df["text"] = [build_text(s, f, p) for s, f, p in zip(df["Subject"], df["From"], df["Preview"])]
    conflict = df.groupby("text")["label_key"].nunique()
    conflict = conflict[conflict > 1]
    if len(conflict):
        ids = df[df["text"].isin(conflict.index)][["review_id", "label_key"]].values.tolist()
        raise DataError(f"[{task}] {len(conflict)} identical model inputs with different labels: {ids[:6]}")
    n_before = len(df)
    df = df.drop_duplicates("text").reset_index(drop=True)
    counts = df["label_key"].value_counts()
    model_labels = [l for l in labels if l not in rule_labels]
    missing = [l for l in model_labels if counts.get(l, 0) == 0]
    if missing and not allow_missing:
        raise DataError(f"[{task}] app labels with no training examples: {missing}. "
                        f"Add labelled emails before training.")
    small = {l: int(c) for l, c in counts.items() if c < 5}
    if small:
        raise DataError(f"[{task}] labels with < 5 unique inputs (cannot split): {small}")
    supported = [l for l in model_labels if l in counts.index]
    info = {"rows_used": len(df), "duplicates_removed": n_before - len(df),
            "rule_rows_excluded": len(ruled), "rule_labels": rule_labels,
            "sender_rules": SENDER_RULES.get(task, {}),
            "counts": {l: int(counts.get(l, 0)) for l in model_labels},
            "supported_labels": supported, "unsupported_labels": missing}
    return df, info


# --- Synthetic dataset ---
def synthetic_dataset(path, task, labels, real_df):
    """Validate and filter synthetic rows for a task."""
    syn = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in ("Subject", "From", "Preview", task):
        if c not in syn.columns:
            raise DataError(f"[{task}] synthetic CSV is missing column '{c}'")
    vals = syn[task].map(_s)
    bad = sorted(set(vals) - set(labels) - {SKIP, ""})
    if bad:
        raise DataError(f"[{task}] synthetic CSV has unknown labels {bad}")
    rule_labels = set(SENDER_RULES.get(task, {}).values())
    syn = syn.assign(label_key=vals)
    ruled = syn["From"].map(lambda f: sender_rule_label(f, task)).notna()
    syn = syn[~ruled & ~syn["label_key"].isin(rule_labels | {SKIP, ""})].copy()
    syn["text"] = [build_text(a, b, c) for a, b, c in zip(syn["Subject"], syn["From"], syn["Preview"])]
    n0 = len(syn)
    syn = syn.drop_duplicates("text")
    syn = syn[~syn["text"].isin(set(real_df["text"]))]
    near = 0
    if len(syn) and len(real_df):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit(
            list(real_df["text"]) + list(syn["text"]))
        sim = cosine_similarity(vec.transform(syn["text"]), vec.transform(real_df["text"])).max(axis=1)
        near = int((sim >= NEAR_DUP_SIM).sum())
        syn = syn[sim < NEAR_DUP_SIM]
    if "review_id" not in syn.columns or (syn["review_id"] == "").any():
        syn["review_id"] = ["syn_" + hashlib.sha1(t.encode()).hexdigest()[:8] for t in syn["text"]]
    syn = syn.reset_index(drop=True)
    info = {"rows": len(syn), "removed_duplicates": n0 - len(syn) - near,
            "removed_near_real": near,
            "counts": {l: int((syn["label_key"] == l).sum()) for l in labels if l not in rule_labels}}
    return syn, info


# --- Train/val/test split ---
def split_dataset(df, seed=SEED):
    from sklearn.model_selection import train_test_split
    trval, test = train_test_split(df, test_size=0.2, random_state=seed, stratify=df["label_key"])
    train, val = train_test_split(trval, test_size=0.2 / 0.8, random_state=seed, stratify=trval["label_key"])
    for a, b in ((train, val), (train, test), (val, test)):
        assert not set(a["text"]) & set(b["text"]), "split leakage"
    return train.reset_index(drop=True), val.reset_index(drop=True), test.reset_index(drop=True)
