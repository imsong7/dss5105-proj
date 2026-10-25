# dss5105-proj — Email Classification Project

Flask email sorter with Llama (Ollama) and BERT backends, plus offline quality and operational benchmarks.

| Folder | Purpose |
|--------|---------|
| `email-sorter/` | Flask app: fetch, classify, filter, and compare backends. |
| `bert/` | BERT training: frozen-encoder heads and optional DistilBERT fine-tunes. |
| `evaluation/` | Offline OOF quality and operational performance benchmarks. |

## Quick start

### App
```bash
cd email-sorter
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
python run.py
```

Open <http://127.0.0.1:5000>. Choose **Llama** or **BERT** in the sidebar; `MODEL_BACKEND` only sets the initial default.

- Llama: run `ollama pull llama3.1:8b` and keep Ollama running.
- BERT: train the heads below first.

Pages:
- `/` — sort one mailbox batch.
- `/compare` — run several backends on the same batch and export CSV.

### BERT training and evaluation
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python bert/train.py --check-only
python bert/train.py --task category
python bert/train.py --task action --synthetic bert/data/synthetic.csv
python bert/train.py --mode full --task both   # optional DistilBERT fine-tune
```

See `bert/README.md` for details.

### Evaluation
```bash
python evaluation/offline_quality.py
python evaluation/offline_quality.py --no-synthetic
python evaluation/operational_performance.py
python -m unittest evaluation.test_evaluation -v
```

Results go to `evaluation/results/`. See `evaluation/README.md` for methodology and caveats.

## Model recommendation

| Task | Model | OOF macro-F1 (95% CI) |
|------|-------|-----------------------|
| Category | `bert/models/category_head` (bge-small-en) | **0.844** [0.780, 0.905] model-only; **0.870** [0.813, 0.919] end-to-end |
| Action | `bert/models/action_head` (e5-small-multi + synthetic) | **0.795** [0.707, 0.871] real+synthetic; 0.697 real-only |

These are 5-fold out-of-fold estimates. The app feeds BERT the email body, falling back to the 200-character preview, truncated at 256 tokens.

Operational benchmark (30 emails, 5 runs, seed 42): BERT heads run at 32.9 / 40.8 ms warm p50/p95 with 921 MB peak memory; Llama 3.1 8B at 3,298 / 5,334 ms with 5.7 GB. Full results and caveats are in `evaluation/README.md`.

## Project layout

- `email-sorter/app/` — Flask routes, backends, taxonomy, sender rules, email providers.
- `email-sorter/static/` and `templates/` — shared UI for sorter and comparison pages.
- `bert/train.py` — unified trainer (`--mode head|full`).
- `bert/src/` — data loading, synthetic generation, model training.
- `bert/data/` — labelled and synthetic training data.
- `evaluation/` — evaluators, tests, and committed result artifacts.
- `CHANGES.md` — change log.
