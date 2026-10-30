# Model comparison — all committed results

Extracted from the reports and artifacts in the repo on 2026-10-30.
**Do not compare numbers across sections directly**: the splits and protocols
differ (CV, holdout, 27-email test, OOF, different sample sizes).

Source files are listed under each table.

---

## 1. What the app uses now

| Backend | Category model | Action model |
|---|---|---|
| `hybrid_claude` (default) | LinearSVC (`C=10`, balanced) | Claude `claude-haiku-5-5` |
| `hybrid` | LinearSVC (`C=10`, balanced) | text-encoder `e5-small-multi` head |
| `ml` | LinearSVC (`C=10`, balanced) | BalancedComplementNB (`alpha=3`) |
| `encoder` | `bge-small-en` head | `e5-small-multi` head |
| `llm` | Llama 3.1 8B via Ollama | Llama 3.1 8B via Ollama |
| `claude` | Claude `claude-haiku-5-5` | Claude `claude-haiku-5-5` |

The two ML artifacts are task-specific:

- `classical-ml/artifacts/email_category_model.joblib` — LinearSVC
- `classical-ml/artifacts/required_action_model.joblib` — BalancedComplementNB

---

## 2. Classical ML — full model comparison

Protocol: 5×5 repeated stratified CV on real emails; the 27-email holdout is a
sanity check and is **not** used for selection. Synthetic rows are added only to
`required_action` training folds.

Source: `classical-ml/reports/model_comparison.md`

### Category (`email_category`)

| Model | CV macro F1 | CV accuracy | Holdout macro F1 | Holdout accuracy |
|---|---:|---:|---:|---:|
| complement_nb_balanced | 0.873 ± 0.021 | 0.886 ± 0.017 | 0.830 | 0.889 |
| logistic_regression | 0.865 ± 0.021 | 0.880 ± 0.017 | 0.831 | 0.889 |
| linear_svm | 0.861 ± 0.018 | 0.881 ± 0.016 | 0.833 | 0.889 |
| complement_nb | 0.823 ± 0.018 | 0.862 ± 0.016 | 0.830 | 0.889 |
| xgboost | 0.795 ± 0.024 | 0.806 ± 0.023 | 0.738 | 0.778 |
| random_forest | 0.768 ± 0.016 | 0.800 ± 0.013 | 0.739 | 0.778 |
| multinomial_nb | 0.660 ± 0.012 | 0.752 ± 0.011 | 0.672 | 0.778 |
| majority_baseline | 0.082 ± 0.000 | 0.258 ± 0.000 | 0.082 | 0.259 |

### Action (`required_action`)

| Model | CV macro F1 | CV accuracy | Holdout macro F1 | Holdout accuracy |
|---|---:|---:|---:|---:|
| complement_nb_balanced | 0.697 ± 0.023 | 0.812 ± 0.008 | 0.820 | 0.889 |
| complement_nb | 0.672 ± 0.029 | 0.821 ± 0.014 | 0.820 | 0.889 |
| linear_svm | 0.653 ± 0.049 | 0.825 ± 0.021 | 0.726 | 0.852 |
| xgboost | 0.592 ± 0.034 | 0.743 ± 0.015 | 0.492 | 0.778 |
| random_forest | 0.557 ± 0.019 | 0.809 ± 0.007 | 0.518 | 0.778 |
| multinomial_nb | 0.551 ± 0.049 | 0.809 ± 0.020 | 0.471 | 0.815 |
| logistic_regression | 0.547 ± 0.043 | 0.808 ± 0.006 | 0.336 | 0.741 |
| majority_baseline | 0.211 ± 0.000 | 0.732 ± 0.000 | 0.213 | 0.741 |

---

## 3. Classical ML — selected / tuned models

The selected models use tuned hyperparameters, so their CV scores are higher
than the default-config scores in section 2.

Source: `classical-ml/reports/hyperparameter_tuning_best.csv`

| Task | Selected model | CV macro F1 | CV accuracy | Holdout macro F1 | Holdout accuracy |
|---|---|---:|---:|---:|---:|
| `email_category` | `linear_svm`, C=10, ngram (1,2), min_df=2, max_df=0.90 | **0.906 ± 0.015** | 0.909 | 0.833 | 0.889 |
| `required_action` | `complement_nb_balanced`, alpha=3, ngram (1,2), min_df=1, max_df=0.90, sublinear | **0.688 ± 0.031** | 0.820 | 0.820 | 0.889 |

---

## 4. Synthetic data ablation — action task

Protocol: 5×5 repeated stratified CV; 134 real emails, 200 synthetic rows.

Source: `classical-ml/reports/ablation_synthetic.md`

| Model | Real-only macro F1 | + Synthetic macro F1 | Delta | + Synthetic accuracy |
|---|---:|---:|---:|---:|
| complement_nb | 0.403 ± 0.014 | 0.672 ± 0.029 | +0.270 | 0.821 ± 0.014 |
| complement_nb_balanced | 0.440 ± 0.034 | 0.697 ± 0.023 | +0.257 | 0.812 ± 0.008 |
| linear_svm | 0.421 ± 0.022 | 0.653 ± 0.049 | +0.231 | 0.825 ± 0.021 |

The action models depend heavily on the synthetic rows. Do not quote the
`+ Synthetic` result as a real-email-only result.

---

## 5. Text-encoder heads — action task, real vs synthetic

Protocol: frozen encoder + logistic-regression head, 2 seeds, test = real emails
only.

Source: `text-encoders/results/compare_head_summary.txt`

| Encoder | Real macro F1 | Real accuracy | + Synthetic macro F1 | + Synthetic accuracy |
|---|---:|---:|---:|---:|
| `bge-small-en` | 0.542 ± 0.123 | 0.741 | 0.714 ± 0.188 | 0.833 |
| `e5-small-multi` | 0.601 ± 0.009 | 0.815 | **0.774 ± 0.047** | **0.870** |
| `distilbert-mean` | **0.654 ± 0.093** | 0.759 | 0.690 ± 0.001 | 0.796 |

Two seeds is a small sample; the bge rows vary a lot. `e5-small-multi + synthetic`
is the selected action head for the `encoder`/`hybrid` backends.

---

## 6. Trained encoder models — single 27-email test split

Source: `text-encoders/models/*/metrics.json` (`test` section)

| Model | Task | Test accuracy | Test macro F1 |
|---|---|---:|---:|
| `category_head` (bge-small-en) | category | 0.889 | 0.865 |
| `category_full` (DistilBERT fine-tune) | category | 0.889 | 0.860 |
| `action_head` (e5-small-multi) | action | 0.778 | 0.511 |
| `action_full` (DistilBERT fine-tune) | action | 0.815 | 0.675 |

Single run, 27 test rows. The action split has only 3 `needs_action`, 2
`needs_reply`, 2 `reminder`, and 20 `no_immediate_action` rows.

---

## 7. Text encoder vs classical ML — shared holdout

Source: `classical-ml/artifacts/shared_bert_ml_results/summary.csv`

| Model | Task | n | Accuracy | Macro F1 |
|---|---|---:|---:|---:|
| encoder | category | 27 | 0.889 | 0.716 |
| ml | category | 27 | 0.889 | 0.694 |
| encoder | action | 7 | 1.000 | 0.500 |
| ml | action | 7 | 1.000 | 0.500 |
| encoder | both exact match | 3 | 0.667 | — |
| ml | both exact match | 3 | 0.667 | — |

Operations from the same file:

| Model | Median latency | p95 latency | Error rate | Invalid category | Invalid action |
|---|---:|---:|---:|---:|---:|
| encoder | 31.2 ms | 52.9 ms | 0.0 | 0.0 | 0.0 |
| ml | 0.65 ms | 4.76 ms | 0.0 | 0.0 | 0.0 |

The action/both sample sizes are too small to rank the models.

---

## 8. Four-method evaluation — older run on this branch

These artifacts predate the Claude integration and the current default backend.
The ML action row is **real-data only**, so it is not the production
`complement_nb_balanced + synthetic` result.

Source: `evaluation/results/quality_summary.csv`

| Method | Category accuracy | Category macro F1 | Action accuracy | Action macro F1 | Both exact match |
|---|---:|---:|---:|---:|---:|
| encoder | 0.864 | 0.844 | 0.784 | 0.697 | 0.695 |
| ml | 0.886 | 0.867 | 0.373 | 0.392 | 0.336 |
| llm | 0.720 | 0.648 | 0.776 | 0.652 | 0.580 |

Source: `evaluation/results/performance_summary.csv`

| Backend | Warm p50 | Peak memory | Invalid rate | Consistency |
|---|---:|---:|---:|---:|
| encoder | 69.7 ms | 1122 MB | — | 1.000 |
| ml | 1.06 ms | 797 MB | — | 1.000 |
| llama | 12,622 ms | 6321 MB | 0.000 | 1.000 |

Claude is not in these old artifacts. The current evaluator supports
`--model claude`, so rerun the scripts for a fresh four-method comparison.

### Latest known Claude run (integration branch)

These numbers are from the Claude integration run on the other branch; they are
not present in this branch's `evaluation/results/`.

| Method | Category accuracy | Category macro F1 | Action accuracy | Action macro F1 | Both exact match |
|---|---:|---:|---:|---:|---:|
| claude | 0.833 | 0.826 | 0.888 | 0.826 | 0.748 |

| Backend | Warm p50 | Peak memory | Input tokens | Output tokens | Invalid rate |
|---|---:|---:|---:|---:|---:|
| claude | 1,149 ms | 678 MB | 992 | 60 | 0.000 |

n=10 for the Claude performance run (`--claude-limit 10`), so its latency and
memory are not directly comparable to the 30-email backends.

---

## 9. Which number should I quote?

| Claim | Use |
|---|---|
| Best classical-ML model per task | section 3 (tuned CV) |
| All classical-ML models under the same CV | section 2 |
| Effect of synthetic data on action | section 4 |
| Best encoder head for action | section 5 |
| App backend quality | section 8, then rerun `python evaluation/quality.py --model all` to include Claude |
| Operational latency/memory | section 8, then rerun `python evaluation/performance.py --model all` |

The cleanest like-for-like comparison is the `evaluation/` run: same emails,
same metrics, same protocol. The model reports in sections 2–7 are useful for
model selection, not for ranking the four app methods.
