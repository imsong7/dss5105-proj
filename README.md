# Email Classification Project

Flask email sorter with Llama (Ollama) and BERT backends.

| Folder | Purpose |
|--------|---------|
| `email-sorter/` | Flask app for fetching, classifying, and comparing email backends. |
| `bert/` | BERT training and model artifacts. |
| `evaluation/` | Model quality and operational benchmarks. |

## Quick start

### Run the app
```bash
cd email-sorter
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
python run.py
```

Open <http://127.0.0.1:5000>. Choose **Llama** or **BERT** in the sidebar; `MODEL_BACKEND` only sets the initial default.

Llama requires `ollama pull llama3.1:8b` and Ollama running. Train BERT before selecting it.

### BERT training and evaluation
From the project root:

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

See `evaluation/README.md` for model comparison, metrics, and methodology.

## Model recommendation

| Task | Model | OOF macro-F1 (95% CI) |
|------|-------|-----------------------|
| Category | `bert/models/category_head` (bge-small-en) | **0.844** [0.780, 0.905] model-only; **0.870** [0.813, 0.919] end-to-end |
| Action | `bert/models/action_head` (e5-small-multi + synthetic) | **0.795** [0.707, 0.871] real+synthetic; 0.697 real-only |

Scores are 5-fold out-of-fold estimates. BERT uses the email body, falling back to the 200-character preview, with a 256-token limit.

Operational benchmark (30 emails, 5 runs, seed 42): BERT warm p50/p95 is 32.9/40.8 ms (921 MB peak); Llama is 3,298/5,334 ms (5.7 GB peak). See `evaluation/README.md` for details.

## Project layout

- `email-sorter/app/` — Flask routes, backends, taxonomy, sender rules, email providers.
- `email-sorter/static/` and `templates/` — app UI.
- `bert/train.py` — unified trainer (`--mode head|full`).
- `bert/src/` — data loading, synthetic generation, model training.
- `bert/data/` — labeled and synthetic training data.
- `evaluation/` — evaluators and tests.
