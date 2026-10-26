# Email Classification Project

This project compares a Flask email sorter, frozen-encoder and fine-tuned
neural models, and classical TF-IDF classifiers.

| Folder | Purpose |
|--------|---------|
| `email-sorter/` | Flask app, email providers, model backends, and dashboards. |
| `bert/` | Frozen BGE/E5/DistilBERT heads and optional DistilBERT fine-tuning. |
| `ML/` | Classical TF-IDF model training, tuning, and synthetic-data experiments. |
| `evaluation/` | Quality and operational evaluation scripts. |

The ML models are research baselines and are not currently wired into the app.

## Run the app

```bash
cd email-sorter
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
ollama pull llama3.1:8b
python run.py
```

Open <http://127.0.0.1:5000>. Llama requires Ollama running. BERT requires
trained heads; choose a backend in the sidebar or set `MODEL_BACKEND`.

## Train neural models

Run from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bert/train.py --check-only
python bert/train.py --task category
python bert/train.py --task action --synthetic bert/data/synthetic.csv
```

Optional DistilBERT fine-tuning:

```bash
python bert/train.py --mode full --task both
```

See [bert/README.md](bert/README.md) for model and training details.

## Train classical ML models

The real-label workbook is private and is not committed. Obtain `labels.xlsx`
from the team, place it in `ML/`, then run from that directory:

```bash
cd ML
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-ml.txt
python train_email_ml.py
python compare_models.py
python tune_models.py
python ablation_synthetic.py
```

See [ML/README.md](ML/README.md) for the workbook format and result caveats.

## Evaluation

```bash
python evaluation/offline_quality.py
python evaluation/operational_performance.py
python -m unittest evaluation.test_evaluation evaluation.test_compare_models -v
```

See [evaluation/README.md](evaluation/README.md) for metrics and model
comparison guidance. The ML reports use a separate workbook and label scheme;
their scores should not be directly compared with the neural-model scores
until both pipelines use the same reviewed examples, labels, inputs, and
held-out split.

## Project layout

- `email-sorter/app/`: app routes, classifier backends, taxonomy, rules, and providers.
- `bert/train.py` and `bert/src/`: neural-model training and data preparation.
- `ML/`: classical-model experiments and local-only trained artifacts.
- `evaluation/`: shared and model-specific evaluation scripts and tests.
