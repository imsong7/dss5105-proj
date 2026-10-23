"""Data handling for BERT email classification.

Includes: review CSV loading/validation, stratified train/val/test split,
synthetic dataset creation, and helper utilities.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import random

import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
TAXONOMY_PATH = os.path.join(REPO_DIR, "email-sorter", "app", "taxonomy.py")

SEED = 42
MAX_LEN = 256
STRIP_SENDER = True
BATCH_SIZE = 16
LR = 5e-5
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01
HEAD_C = 10.0  # inverse L2 strength of the logistic-regression head

TASKS = {"category": "CONTENT_CATEGORIES", "action": "REPLY_NATURE"}

# Legacy sheet -> app key. Earlier sheets win when an email appears in several.
CATEGORY_SHEETS = {
    "ak-reminder": "others",
    "ak-FoS": "general",
    "ak-others": "others",
    "medical": "medical",
    "promotion": "promotional",
    "career+external emails": "career",
    "others": "others",
    "ssy - canvas": "canva",
}
CAREER_OVERRIDES = [
    ("Mahin's Manchester", "others"),
    ("Enveda CASMI", "others"),
    ("Requesting data set", "others"),
    ("Save $519 on the LG Gram", "promotional"),
    ("N2CR Invited Speaker", "others"),
    ("Where's your next opportunity", "promotional"),
    ("OpenAI says GPT-6 won", "promotional"),
]
ACTION_SHEETS = {
    "ssy - need a reply": "needs_reply",
    "ssy - ignore": "no_immediate_action",
    "ak-ignore": "no_immediate_action",
    "ak-need an action": "needs_action",
    "ak-need a reply": "needs_reply",
}
SENDER_RULES = {
    "category": {"notifications@instructure.com": "canva"},
}
# name -> (HF model id, text prefix, pooling)
ENCODERS = {
    "bge-small-en": ("BAAI/bge-small-en-v1.5", "", "cls"),
    "e5-small-multi": ("intfloat/multilingual-e5-small", "query: ", "mean"),
    "distilbert-mean": ("distilbert-base-uncased", "", "mean"),
}
PAYMENT_WORDS = ("payment", "fees", "giro")

SKIP = "__skip__"
XLSX = os.path.join(SCRIPT_DIR, "..", "data_1012.xlsx")

NEAR_DUP_SIM = 0.8  # TF-IDF cosine; synthetic rows this close to any real email are dropped


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def _s(v):
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else str(v).strip()


def build_text(subject, from_addr, preview, strip_sender=STRIP_SENDER):
    if strip_sender:
        return f"Subject: {_s(subject)}\n{_s(preview)}"
    return f"From: {_s(from_addr)}\nSubject: {_s(subject)}\n{_s(preview)}"


def content_key(subject, from_addr, preview):
    return f"{_s(subject).lower()}||{_s(from_addr).lower()}||{_s(preview).lower()}"


def sender_address(from_field):
    from email.utils import parseaddr
    return parseaddr(_s(from_field))[1].strip().lower()


def sender_rule_label(from_field, task):
    return SENDER_RULES.get(task, {}).get(sender_address(from_field))


# --------------------------------------------------------------------------- #
# Taxonomy
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Review CSV building (from legacy Excel sheets)
# --------------------------------------------------------------------------- #
def build_records(xlsx=XLSX):
    """Merge every labeled sheet into one record per email with Category + Action."""
    xl = pd.ExcelFile(xlsx)
    known = set(CATEGORY_SHEETS) | set(ACTION_SHEETS)
    unknown = [s for s in xl.sheet_names if s not in known]
    if unknown:
        print(f"[warn] sheets not mapped to any label (ignored): {unknown}")
    recs = {}
    order = list(CATEGORY_SHEETS) + list(ACTION_SHEETS)
    for sheet in order:
        if sheet not in xl.sheet_names:
            continue
        df = xl.parse(sheet, dtype=object)
        for _, r in df.iterrows():
            subj, frm, prev = _s(r.get("Subject")), _s(r.get("From")), _s(r.get("Preview"))
            if not (subj or frm or prev):
                continue
            k = content_key(subj, frm, prev)
            rec = recs.setdefault(k, {
                "review_id": hashlib.sha1(k.encode()).hexdigest()[:12],
                "Subject": subj, "From": frm, "Preview": prev,
                "Received DateTime": _s(r.get("Received DateTime")),
                "source_sheets": [], "legacy_category": "", "legacy_action": ""})
            rec["source_sheets"].append(sheet)
            if sheet in CATEGORY_SHEETS and not rec["legacy_category"]:
                cat = CATEGORY_SHEETS[sheet]
                if sheet == "career+external emails":
                    for pat, new in CAREER_OVERRIDES:
                        if pat.lower() in subj.lower():
                            cat = new
                rec["legacy_category"] = cat or ""
            if sheet in ACTION_SHEETS and not rec["legacy_action"]:
                rec["legacy_action"] = ACTION_SHEETS[sheet]
    out = pd.DataFrame(recs.values())
    out["source_sheets"] = out["source_sheets"].apply(lambda s: "+".join(dict.fromkeys(s)))
    return out


def suggest_category(rec):
    rule = sender_rule_label(rec["From"], "category")
    if rule:
        return rule, "sender rule (excluded from model training)"
    if rec["legacy_category"]:
        return rec["legacy_category"], "legacy sheet"
    return "", ""


def suggest_action(rec):
    sheets = rec["source_sheets"].split("+")
    if "ak-reminder" in sheets:
        if any(w in rec["Subject"].lower() for w in PAYMENT_WORDS):
            return "needs_action", "reminder sheet, but asks for payment (priority rule)"
        if rec["legacy_action"] in ("needs_action", "needs_reply"):
            return rec["legacy_action"], "reminder sheet, higher-priority legacy label kept"
        return "reminder", "reminder sheet: date/time, no action asked"
    if rec["legacy_action"]:
        return rec["legacy_action"], "legacy sheet"
    return "", ""


def export_review(path, prefill=False):
    """Build and write a review CSV for manual labeling."""
    rec = build_records()
    sc = rec.apply(suggest_category, axis=1, result_type="expand")
    sa = rec.apply(suggest_action, axis=1, result_type="expand")
    rec["suggested_category"], rec["category_note"] = sc[0], sc[1]
    rec["suggested_action"], rec["action_note"] = sa[0], sa[1]
    if prefill:
        rec["category"] = rec["suggested_category"].replace("", SKIP)
        rec["action"] = rec["suggested_action"].replace("", SKIP)
        rec["label_source"] = "provisional"
    else:
        rec["category"], rec["action"], rec["label_source"] = "", "", ""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    rec.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(rec)} unique emails to {path} (prefill={prefill})")
    print("suggested category:", rec["suggested_category"].replace("", "(none)").value_counts().to_dict())
    print("suggested action  :", rec["suggested_action"].replace("", "(none)").value_counts().to_dict())


# --------------------------------------------------------------------------- #
# Review CSV -> validated task datasets
# --------------------------------------------------------------------------- #
def task_dataset(review, task, labels, allow_missing=False):
    col = task
    vals = review[col].fillna("").astype(object).map(_s)
    blank = review[vals == ""]
    if len(blank):
        raise DataError(f"[{task}] {len(blank)} rows not reviewed. Fill an app key or {SKIP}.")
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
                        f"Add labelled emails, or pass --allow-missing-labels.")
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


# --------------------------------------------------------------------------- #
# Synthetic dataset
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Train/val/test split
# --------------------------------------------------------------------------- #
def split_dataset(df, seed=SEED):
    from sklearn.model_selection import train_test_split
    trval, test = train_test_split(df, test_size=0.2, random_state=seed, stratify=df["label_key"])
    train, val = train_test_split(trval, test_size=0.2 / 0.8, random_state=seed, stratify=trval["label_key"])
    for a, b in ((train, val), (train, test), (val, test)):
        assert not set(a["text"]) & set(b["text"]), "split leakage"
    return train.reset_index(drop=True), val.reset_index(drop=True), test.reset_index(drop=True)
