# BERT training pipeline — real data verification report

> **Historical snapshot** of commit `05327ce` (pre-refactor). Paths, commands,
> and results may not match the current code. See `README.md` and
> `bert/README.md` for the current training workflow.

- Repository: imsong7/dss5105-proj (commit 05327ce)
- Environment: CPU 2-core, Python 3 / pandas 3.0.6 / torch 2.14.1+cpu / transformers 5.20.2 / datasets 5.1.0
- Base model: `distilbert-base-uncased` (verified download from Hugging Face)
- Label reference: `email-sorter/app/taxonomy.py` (sha256 first 16 chars `99e9c2be07f026dd`)

## 1. Excel processing

| Item | Result |
|------|--------|
| Sheets / non-empty rows | 13 / 282 rows |
| Unique emails after dedup | 202 |
| Category training rows used | 196 (`__skip__` 5, duplicate input 1 excluded) |
| Action training rows used | 75 (127 rows with no action label are `__skip__`) |

### Found bug: pandas 3 silently drops rows

`preprocess.py` `_key()` uses `astype(str)`, but in pandas 3 NaN stays as NaN instead of becoming `"nan"`. Sheets with empty Message ID (medical, promotion, ssy-*) get NaN keys and are dropped by `groupby`, leaving only 49 of 202 rows. Fixed by adding one line `fillna("")`; after the fix row counts match the repo's existing CSVs (category 129, action 65). The old patch file has since been removed; the change was `df["Internet Message ID"].fillna("").astype(str).str.strip()`.

### Found data characteristics

- Excel `Preview` column averages ~1,840 chars (max 48,000), effectively the full body. The app's `Email.preview` is truncated to 200 chars.
- App `canva` (Canva design service) examples: 0 rows. No `canva.com` sender or Canva mentions at all.
- `ssy - canvas` sheet: 74 rows (67 unique), all from `notifications@instructure.com` (Canvas LMS).

## 2. Provisional labels

Before human review, `--prefill` labels were filled using the rules below for verification. All rows have `label_source=provisional`.

| Target | Provisional label | Reason |
|--------|-------------------|--------|
| Original sheet label | 1:1 mapped to app key | Medical → medical, etc. |
| Canvas LMS emails, 67 rows | `general` | App description "university announcements, lecturers" |
| `ak-reminder` sheet with payment/fees/giro in subject | `needs_action` | App priority needs_action > reminder |
| `ak-reminder` sheet, remaining 7 rows | `reminder` | Date given, no action required |
| Emails with no action label | `__skip__` | Do not guess |

## 3. Verification checks (real data)

| Scenario | Result |
|----------|--------|
| Empty review CSV | Stops after 202 un-reviewed rows (exit 2) |
| Provisional labels, strict mode | Stops: 0 `canva` examples (exit 2) |
| Provisional labels + `--allow-missing-labels` | Passes, `canva` recorded in manifest `unsupported_labels` |
| Split | Category 117/39/40, action 45/15/15, no duplicates across splits |

## 4. Compatibility issues found and fixed during training

- transformers 5 removed `evaluation_strategy` and `warmup_ratio` args, so `TrainingArguments` fails.
  `train_full.py` uses `eval_strategy` and computed `warmup_steps`.
  Old `train.py` also fails under transformers 5 for the same reason.
- Fixed manifest numpy bool failing to save to JSON.
- Changed defaults to `--epochs 10`, `--lr 5e-5` and added `--lr` option.

## 5. Training and evaluation results

Best epoch chosen by validation macro-F1 only; test evaluated once at the end.

### Test results by config

| Config | Category acc / macro-F1 | Action acc / macro-F1 |
|--------|-------------------------|-----------------------|
| 4 epochs, lr 2e-5 | 0.600 / 0.485 | 0.600 / 0.458 |
| 10 epochs, lr 2e-5 | 0.675 / 0.570 | 0.733 / 0.754 |
| **10 epochs, lr 5e-5 (final)** | **0.825 / 0.754** | **0.800 / 0.810** |
| Baseline: most frequent class | 0.400 / 0.114 | 0.667 / 0.200 |
| Baseline: TF-IDF + logistic regression | 0.825 / 0.818 | 0.667 / 0.446 |

At lr 2e-5, validation score kept rising through 10 epochs — under-trained.

### Final model per-class test F1 (support count)

- Category: medical 1.00 (5), promotional 0.86 (6), career 0.33 (5), general 0.91 (16), others 0.67 (8)
- Action: needs_action 0.75 (3), needs_reply 1.00 (1), reminder 0.67 (1), no_immediate_action 0.82 (10)

### Interpretation notes

- Category test has 40 rows, 15 are Canvas emails, all correct. Excluding Canvas, 25 rows accuracy ~0.72.
- `career` is weakest — career event announcements confused with general/others/promotional.
- Action test has 15 rows; reminder and needs_reply each have 1 row, so scores are very unstable.
  Same data with TF-IDF across 10 splits: action macro-F1 0.20–0.68 (std 0.14).
  Category: 0.82–0.97 (mean 0.89).
- Category macro-F1 is still below TF-IDF baseline.

### App input length effect

Truncating Preview to 200 chars (like the app) lowers performance on the same model.

| Input | Category macro-F1 | Action macro-F1 |
|-------|-------------------|-----------------|
| Same as training (long Preview, 256 tokens) | 0.754 | 0.810 |
| App `preview` (200 chars) | 0.590 | 0.754 |

For app integration, use `email.body` (or preview if body missing) in `Subject: ...\n{body}` format, not `email.preview`.

## 6. Saved results

Model weights, tokenizer, `manifest.json`, `metrics.json`, val/test prediction CSVs saved to `bert/models/app_real/{category,action}/` (each ~257MB). `config.json` `id2label` uses app keys as-is.

- Category: `medical, promotional, career, general, others` (`canva` not supported)
- Action: `needs_action, needs_reply, reminder, no_immediate_action`

## 7. Remaining work

1. Have a person review `labels_review_provisional.csv` and finalize (especially Canvas→general, reminder 7 rows, others sheet personal emails 5 rows).
2. Collect and label Canva design emails (at least 5; more needed for real-world performance).
3. Collect more reminder and needs_reply emails (currently 7 and 6 each).
4. Add action labels to the 127 rows without one — action model data grows significantly.
5. App BERT backend: use body input, verify `id2label` matches app keys, expose `unsupported_labels`.
6. Add `bert/model_app/`, `bert/labels_review*.csv` to `.gitignore`.

## Reproduction commands

```bash
python bert/train_full.py --export-review bert/labels_review.csv --prefill
python bert/train_full.py --review bert/labels_review.csv --check-only --allow-missing-labels
python bert/train_full.py --review bert/labels_review.csv --allow-missing-labels --epochs 10 --lr 5e-5
```

CPU 2-core: category ~10 min, action ~4 min.