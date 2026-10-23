# Inbox sorter (Sprint 1 prototype)

Fetches recent emails, classifies each into
(1) content type and (2) reply/action type, and shows the result on a local web page.

## Setup (Windows, VS Code terminal)
    python -m venv .venv
    .venv\Scripts\Activate.ps1   # or: source .venv/bin/activate  (Mac/Linux)
    pip install -r requirements.txt
    copy .env.example .env
    ollama pull llama3.1:8b      # only needed for the "llama" backend
    python run.py
Open http://127.0.0.1:5000

## Model backend selection

Choose the classifier backend with `MODEL_BACKEND` in `.env` or `--backend` on the command line:

| Backend | Description | Requirements |
|---------|-------------|--------------|
| `llama` | Llama via Ollama (default) | `ollama pull llama3.1:8b`, Ollama running |
| `bert` | Frozen BERT encoder + logistic head (tiny, fast) | `bert/models/{task}_head/` trained via `bert/train.py` |

**Examples:**

```bash
# Use Ollama/Llama (default)
python run.py

# Use BERT frozen heads
python run.py --backend bert

# Or via env var
MODEL_BACKEND=bert python run.py
```

Train BERT models first (from repo root, root venv activated):
```bash
.venv/bin/python bert/train.py --review bert/labels.csv --encoder bge-small-en --task category
.venv/bin/python bert/train.py --review bert/labels.csv --encoder e5-small-multi --task action --synthetic bert/synthetic.csv
```

## Where to change things
- Categories and wording: app/taxonomy.py
- Prompt and model call (llama): app/classifier.py
- BERT model wrapper: app/bert_classifier.py
- Classifier base + factory: app/classifier_base.py
- New mail source: add a file in app/providers/ and one line in app/providers/__init__.py
