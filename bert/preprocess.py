#!/usr/bin/env python
"""Data preprocessing for the email classifier.

Reads data_1012.xlsx, merges every labeled sheet into one record per email,
builds the Category + Action datasets, prints label statistics, and can export
leakage-free train/test CSVs.

Usage:
    python preprocess.py                          # print label stats
    python preprocess.py --task category
    python preprocess.py --export                 # also write the CSVs
    python preprocess.py --export --out_dir data

Edit the sheet->label maps below if the taxonomy changes.
"""
import argparse
import os

import pandas as pd
from sklearn.model_selection import train_test_split

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(SCRIPT_DIR, "data_1012.xlsx")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
BASE_COLUMNS = ["Subject", "From", "To", "Received DateTime", "Sent DateTime",
                "Preview", "Has Attachments", "Internet Message ID"]

# sheet -> (task, label). Order matters: earlier sheets win on overlap.
CATEGORY_SHEETS = {
    "ak-reminder": "Others",              # reminders folded into the catch-all
    "ak-FoS": "General",                  # FoS bucket -> General
    "ak-others": "Others",
    "medical": "Medical",
    "promotion": "Promotional",
    "career+external emails": "Career related",
    "others": "Others",
    "ssy - canvas": "Canva (uni app)",
}
# rows in the mixed "career+external" sheet that are really promos/newsletters
CAREER_OVERRIDES = [
    ("Mahin's Manchester", "Others"),
    ("Enveda CASMI", "Others"),
    ("Requesting data set", "Others"),
    ("Save $519 on the LG Gram", "Promotional"),
    ("N2CR Invited Speaker", "Others"),
    ("Where's your next opportunity", "Promotional"),
    ("OpenAI says GPT-6 won", "Promotional"),
]
ACTION_SHEETS = {
    "ssy - need a reply": "Needs a reply",
    "ssy - ignore": "No immediate action",
    "ak-ignore": "No immediate action",
    "ak-need an action": "Needs action",
    "ak-need a reply": "Needs a reply",
}
DATASETS = {"category": "Category", "action": "Action"}

# Deterministic sender rules: substring of the From address -> {label_col: label}.
# Rows matched here are handled without the model and excluded from training.
SENDER_RULES = {
    "instructure.com": {"Category": "Canva (uni app)"},   # Canvas LMS notifications
}

STRIP_SENDER = True     # omit the 'From:' line from the model text
SEED = 42
VAL_SIZE = 0.2          # fraction held out for test


# --------------------------------------------------------------------------- #
# Data building
# --------------------------------------------------------------------------- #
def build_text(subject, from_addr, preview, strip_sender=True):
    subject = "" if pd.isna(subject) else str(subject)
    from_addr = "" if pd.isna(from_addr) else str(from_addr)
    preview = "" if pd.isna(preview) else str(preview)
    if strip_sender:
        return f"Subject: {subject}\n{preview}"
    return f"From: {from_addr}\nSubject: {subject}\n{preview}"


def _clean(df):
    df = df.copy()
    for col in ("Subject", "From", "Preview"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].apply(lambda v: "" if pd.isna(v) else str(v).strip())
    return df[~((df["Subject"] == "") & (df["From"] == "") & (df["Preview"] == ""))].reset_index(drop=True)


def _key(df):
    mid = df["Internet Message ID"].astype(str).str.strip()
    content = (df["Subject"].str.lower() + "||" + df["From"].str.lower() + "||" + df["Preview"].str.lower())
    return mid.where(~mid.str.lower().isin(["", "nan", "none"]), content)


def build_records(xlsx=XLSX):
    """Merge every labeled sheet into one record per email with Category + Action."""
    xl = pd.ExcelFile(xlsx)
    frames = []
    for sheet, category in CATEGORY_SHEETS.items():
        if sheet not in xl.sheet_names:
            continue
        df = _clean(xl.parse(sheet))
        df = df[[c for c in BASE_COLUMNS if c in df.columns]]
        df["Category"] = category
        df["Action"] = pd.NA
        if sheet == "career+external emails":
            for pattern, new_category in CAREER_OVERRIDES:
                mask = df["Subject"].str.contains(pattern, case=False, regex=False)
                df.loc[mask, "Category"] = new_category
        frames.append(df)
    for sheet, action in ACTION_SHEETS.items():
        if sheet not in xl.sheet_names:
            continue
        df = _clean(xl.parse(sheet))
        df = df[[c for c in BASE_COLUMNS if c in df.columns]]
        df["Action"] = action
        df["Category"] = pd.NA
        frames.append(df)

    allrows = pd.concat(frames, ignore_index=True)
    allrows["_key"] = _key(allrows)
    merged = allrows.groupby("_key").first().reset_index(drop=True)
    return merged[BASE_COLUMNS + ["Category", "Action"]]


def task_df(records, label_col, strip_sender=STRIP_SENDER):
    df = records[records[label_col].notna()].copy()
    content = (df["Subject"].str.lower() + "||" + df["From"].str.lower() + "||" + df["Preview"].str.lower())
    df = df.assign(_c=content).drop_duplicates("_c").drop(columns="_c").reset_index(drop=True)
    df["text"] = df.apply(
        lambda r: build_text(r.get("Subject"), r.get("From"), r.get("Preview"), strip_sender), axis=1)
    return df[[c for c in BASE_COLUMNS if c in df.columns] + [label_col, "text"]]


def sender_rule_label(from_addr, label_col):
    """Return the rule label for a sender address, or None if no rule matches."""
    addr = "" if pd.isna(from_addr) else str(from_addr).lower()
    for domain, mapping in SENDER_RULES.items():
        if label_col in mapping and domain in addr:
            return mapping[label_col]
    return None


def split_rule_rows(df, label_col):
    """Separate rows handled by sender rules from rows the model must learn."""
    matched = df["From"].apply(lambda a: sender_rule_label(a, label_col))
    ruled = df[matched.notna()].copy()
    kept = df[matched.isna()].reset_index(drop=True)
    return kept, ruled


def split_train_test(df, label_col, val_size=VAL_SIZE, seed=SEED):
    """Split by email identity (cluster_key) so no email leaks across the split."""
    cluster_key = (df["Subject"].fillna("").astype(str).str.strip().str.lower() + "||"
                   + df["From"].fillna("").astype(str).str.strip().str.lower() + "||"
                   + df["Preview"].fillna("").astype(str).str.strip().str.lower())
    df = df.assign(cluster_key=cluster_key)
    groups = df.drop_duplicates("cluster_key")
    train_groups, test_groups = train_test_split(
        groups, test_size=val_size, random_state=seed, stratify=groups[label_col])
    train_df = df[df["cluster_key"].isin(train_groups["cluster_key"])].drop(columns="cluster_key").reset_index(drop=True)
    test_df = df[df["cluster_key"].isin(test_groups["cluster_key"])].drop(columns="cluster_key").reset_index(drop=True)
    return train_df, test_df


# --------------------------------------------------------------------------- #
# Export / load CSVs for training
# --------------------------------------------------------------------------- #
def export_split(task, df, out_dir=DATA_DIR):
    """Write {task}_train.csv and {task}_test.csv; returns (n_train, n_test)."""
    label_col = DATASETS[task]
    train_df, test_df = split_train_test(df, label_col)
    os.makedirs(out_dir, exist_ok=True)
    train_df.to_csv(os.path.join(out_dir, f"{task}_train.csv"), index=False, encoding="utf-8-sig")
    test_df.to_csv(os.path.join(out_dir, f"{task}_test.csv"), index=False, encoding="utf-8-sig")
    return len(train_df), len(test_df)


def load_split(task, split, out_dir=DATA_DIR):
    """Load an exported {task}_{split}.csv produced by export_split."""
    path = os.path.join(out_dir, f"{task}_{split}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found - run: python preprocess.py --export")
    return pd.read_csv(path)


# --------------------------------------------------------------------------- #
# Label stats
# --------------------------------------------------------------------------- #
def print_stats(task, df, label_col):
    n = len(df)
    labels = sorted(df[label_col].unique().tolist())
    counts = df[label_col].value_counts()
    print(f"\n=== {task}: {n} rows, {len(labels)} labels ===")
    print(f"{'label':<22} {'count':>6} {'pct':>7}")
    print("-" * 37)
    for l in labels:
        print(f"{l:<22} {int(counts[l]):>6} {100 * counts[l] / n:>6.1f}%")
    if len(counts) > 1:
        print(f"Imbalance ratio (max/min): {counts.max() / max(counts.min(), 1):.1f}x")
    tiny = [l for l in labels if counts[l] < 20]
    if tiny:
        print(f"WARNING: tiny classes (<20 rows): {tiny} - per-class F1 will be unstable")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["category", "action", "both"], default="both")
    parser.add_argument("--export", action="store_true", help="write {task}_train.csv / {task}_test.csv")
    parser.add_argument("--out_dir", default=DATA_DIR, help="directory for exported CSVs")
    args = parser.parse_args()

    records = build_records(XLSX)
    for task in (["category", "action"] if args.task == "both" else [args.task]):
        label_col = DATASETS[task]
        df = task_df(records, label_col)
        df, ruled = split_rule_rows(df, label_col)
        if not ruled.empty:
            counts = ruled[label_col].value_counts()
            summary = ", ".join(f"{k} x{v}" for k, v in counts.items())
            print(f"[rule] {len(ruled)} rows handled by sender rule (excluded from training): {summary}")
        print_stats(task, df, label_col)
        if args.export:
            n_train, n_test = export_split(task, df, args.out_dir)
            print(f"Wrote {task}_train.csv ({n_train}) and {task}_test.csv ({n_test}) to {args.out_dir}")


if __name__ == "__main__":
    main()
