# Evaluation

This folder contains the experiment that compares the four email-classification
methods used in the project. It measures two separate things:

- **Quality** — how often each method gets the category and the action right.
- **Operational performance** — how slow, how large and how reliable each method
  is when it actually runs.

Everything is reproducible from the two scripts in this folder; the results in
`results/` were produced by them.

---

## 1. What is compared

| `--model` (quality) | `--model` (performance) | Method | Implementation |
|---|---|---|---|
| `encoder` | `bert` | Frozen text-encoder heads | `email-sorter/app/bert_classifier.py` (bge-small-en for category, e5-small-multi for action) |
| `ml` | `ml` | TF-IDF + LinearSVC / ComplementNB | `email-sorter/app/ml_classifier.py` |
| `llm` | `llm` | Llama 3.1 8B via Ollama | `email-sorter/app/llama_classifier.py` |
| `claude` | `claude` | Anthropic Claude through the inbox-sorter pipeline | `inbox-sorter/` (rules → Claude → guardrails) |

The two scripts use slightly different names for the encoder method: quality calls
it `encoder`, performance calls it `bert`. It is the same classifier.

---

## 2. Data

| File | Rows | Notes |
|---|---|---|
| `data/labels.csv` | 202 | The shared human-reviewed labels (real emails, gitignored). |
| `data/synthetic.csv` | 200 | Synthetic training rows for the action task only. |

The review file has two label columns:

- `category` — `career`, `general`, `medical`, `others`, `promotional`, `canva`.
- `action` — `needs_action`, `needs_reply`, `reminder`, `no_immediate_action`.

After the shared filtering (`src/data.py`), the quality evaluation scores:

- **132 emails** for the category task (Canvas sender-rule rows are excluded,
  because they are classified by a rule, not by the model).
- **134 emails** for the action task.

The action distribution is very unbalanced — about 73 % of the rows are
`no_immediate_action` — which is why macro F1 is reported alongside accuracy.

---

## 3. Metrics

### Quality (`quality.py`)

| Metric | Definition |
|---|---|
| Accuracy | Correct predictions / scored emails. |
| Macro F1 | Unweighted mean of per-class F1. Gives every class equal weight, so a method cannot look good by only predicting the majority class. |

Both metrics are reported separately for the **category** task and the **action**
task. They are not averaged into one number.

### Performance (`performance.py`)

| Metric | Definition |
|---|---|
| Warm latency (p50) | Median latency of measured calls, after warm-up. Lower is better. |
| Peak memory | Highest process RSS observed during the run (for Llama, plus the Ollama server). Lower is better. |
| Tokens | Mean input and output tokens per email. |
| Invalid-output rate | Share of raw responses that fail JSON/label validation. Only Llama and Claude can fail this way; encoder and ML always return a valid label. |

Energy, cold-start latency, model size, run-to-run agreement and short-vs-full
agreement were deliberately left out to keep the comparison focused.

---

## 4. Protocol

### Quality

1. Load `data/labels.csv` and build the category and action datasets with the
   shared filtering in `src/data.py`.
2. **Encoder and ML** are evaluated with **5-fold stratified cross-validation**.
   Each email is scored by a model trained on the other four folds, so no email
   is scored by a model that saw it. Synthetic rows are added to the training
   folds only (action task).
3. **Llama and Claude** are zero-shot: one inference call per unique email, no
   training data. Claude is called through the inbox-sorter pipeline exactly as
   it runs in production (sender rules → Claude → guardrails).
4. Compare per-task accuracy and macro F1.

The encoder/ML families still learn from 80 % of the same dataset the LLM
families never see. This is a real difference between the methods, not a bug:
it is stated here so the numbers are read correctly.

### Performance

1. Sample the benchmark emails (default: 30, stratified by action label).
2. Run `--warmup` calls per backend and discard them.
3. Run `--runs` measured calls per email (default: 5) and report the median
   (p50) latency.
4. Sample memory every 0.15 s for the whole backend run and report the peak.
5. Read token usage from the API response (Llama, Claude) or the tokenizer
   (encoder); ML has no token cost.
6. Count raw outputs that fail JSON/label validation as invalid.

Claude calls cost money, so `--claude-limit N` caps how many emails are sent to
the API. The other backends still use the full sample, and the `N` column in the
report shows each backend's sample size.

---

## 5. How to run

### Prerequisites

```bash
# from the repo root
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- `data/labels.csv` must exist (it is gitignored because it contains real email
  content).
- Llama needs a running Ollama server with the model pulled:
  `ollama pull llama3.1:8b`.
- Claude needs `ANTHROPIC_API_KEY` in `inbox-sorter/.env` and the `anthropic`
  package installed.

### Quality

```bash
# all four methods, both tasks
python evaluation/quality.py --model all

# cheaper: only the two trained families, no API calls
python evaluation/quality.py --model both

# Claude only, capped at 50 emails
python evaluation/quality.py --model claude --claude-limit 50

# one task only
python evaluation/quality.py --model all --task action
```

### Performance

```bash
# all four methods on the default 30-email sample
python evaluation/performance.py --model all

# no paid API calls
python evaluation/performance.py --model llm bert ml

# smaller / cheaper run
python evaluation/performance.py --model all --limit 10 --runs 3 --claude-limit 5
```

### Tests

The unit tests do not call the paid API.

```bash
python -m unittest evaluation.test_evaluation -v
```

---

## 6. Outputs

Both scripts write into `evaluation/results/` by default (`--out-dir` changes it).

| File | Written by | Contents |
|---|---|---|
| `offline_quality_summary.csv` | `quality.py` | Accuracy and macro F1 per method and task. |
| `offline_quality_predictions.csv` | `quality.py` | One row per prediction, for error analysis. |
| `offline_quality_comparison.png` | `quality.py` | Accuracy and macro F1 bar charts. |
| `offline_quality_manifest.json` | `quality.py` | Settings and environment used for the run. |
| `operational_performance_summary.csv` | `performance.py` | Latency, memory, tokens and invalid rate per backend. |
| `operational_performance_runs.csv` | `performance.py` | Raw per-call measurements. |
| `operational_performance_comparison.png` | `performance.py` | Warm latency and peak memory bar charts. |
| `operational_performance_manifest.json` | `performance.py` | Sample, settings and environment used for the run. |
| `rubric_alignment.csv` | one-off analysis | Per-class action recall before/after aligning the inbox-sorter rubric. |

All CSV files are UTF-8 with a BOM so they open cleanly in Excel.

---

## 7. Results from the committed run

### Quality

| Method | Category accuracy | Category macro F1 | Action accuracy | Action macro F1 |
|---|---:|---:|---:|---:|
| Encoder | 0.864 | 0.844 | 0.843 | 0.735 |
| Classical ML | **0.886** | **0.867** | 0.806 | 0.693 |
| Llama | 0.720 | 0.648 | 0.776 | 0.652 |
| Claude | 0.833 | 0.826 | **0.888** | **0.826** |

n = 132 (category), 134 (action).

Claude has the best action scores; classical ML has the best category scores.
Llama is the weakest of the four on both tasks.

### Operational performance

| Backend | N | Warm p50 (ms) | Peak memory (MB) | Input tokens | Output tokens | Invalid rate |
|---|---:|---:|---:|---:|---:|---:|
| Llama | 30 | 12,114 | 892 | 650 | 55 | 0.0 |
| Encoder | 30 | 74 | 862 | 352 | 0 | — |
| Classical ML | 30 | **2.1** | **679** | — | 0 | — |
| Claude | 10 | 1,149 | 678 | 992 | 60 | 0.0 |

Claude's N is 10 because the committed run used `--claude-limit 10`, so its
latency and memory are not directly comparable to the 30-email backends. Rerun
without the limit for a like-for-like table.

---

## 8. Limitations

- **Small sample.** 132–134 emails, and only 9 `needs_reply` rows in the action
  task. Differences of a few points are not statistically strong.
- **Label quality.** The labels were merged from earlier sheets; some rows are
  inconsistent or debatable. An earlier Cleanlab audit flagged about 13 % of the
  action labels as suspected issues.
- **Training access differs.** Encoder/ML learn from the same labelled pool
  (out-of-fold, so no row is self-scored), while Llama and Claude are zero-shot.
- **Claude is a pipeline, not just a model.** The inbox-sorter adds sender rules
  and a confidence guardrail, so the Claude row measures the whole system.
- **Latency is machine-specific.** Numbers depend on this laptop and, for
  Claude, on network conditions.
- **Performance sample is small.** 30 emails × 5 runs is enough for a stable
  median but not for fine-grained comparisons.
