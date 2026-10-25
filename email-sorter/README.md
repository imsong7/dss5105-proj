# Inbox sorter

Fetches recent emails and classifies each into (1) content type and
(2) reply/action type. The Flask app has two pages:

| Page | Purpose |
|------|---------|
| `/` | Sort one batch with a chosen backend, filter by category/action, retry failures. |
| `/compare` | Run the same batch through several backends, compare labels and latency, export CSV. |

## Setup (Windows, VS Code terminal)
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # or: source .venv/bin/activate  (Mac/Linux)
pip install -r requirements.txt
copy .env.example .env
python run.py
# Open http://127.0.0.1:5000
```

`requirements.txt` covers both backends (Flask + HTTP providers, LangChain/Ollama,
and torch/transformers for BERT).

## How the comparison page works

- Fetches the mailbox batch once.
- Runs one backend at a time, so models are not reloaded for every email and
  the two runs do not compete for CPU.
- Optionally warms up each backend first; the warm-up request is excluded from
  the per-email averages.
- Shows per-backend total/average/median/p95 latency, a pairwise label-agreement
  matrix, and a per-email table. Results can be exported as CSV.

## Choosing a backend

Pick **Llama** or **BERT** in the sidebar. The choice is saved in your browser
and does not require a server restart.

`MODEL_BACKEND` in `.env` (or `--backend` on the command line) only sets the
**initial default** for a browser with no saved choice:

```bash
# Optional: change the server default
python run.py --backend bert
MODEL_BACKEND=llama python run.py
```

| Backend | Description | Requirements |
|---------|-------------|--------------|
| `llama` | Llama via Ollama | `ollama pull llama3.1:8b`, Ollama running |
| `bert` | Frozen BERT encoder + logistic head (tiny, fast) | `bert/models/{category,action}_head/` trained via `bert/train.py` |

The list of backends comes from `/api/backends`, which reads the registry in
`app/classifier_base.py`. To add a model later:

1. Implement `BaseClassifier` (see `app/classifier.py` or `app/bert_classifier.py`).
2. Add metadata to `BACKEND_INFO` in `app/classifier_base.py`.
3. Add a branch in `create_classifier()`.

The Sorter and Compare pages render it automatically.

## Train BERT models

From the repo root, with the root `.venv` activated:

```bash
.venv/bin/python bert/train.py --task category
.venv/bin/python bert/train.py --task action --synthetic bert/data/synthetic.csv
```

Models are written to `bert/models/{task}_{head,full}/`. The app uses the `_head`
variants by default. Large `model.safetensors` files are ignored by Git.

## API

| Route | Purpose |
|-------|---------|
| `GET /` | Sorter page |
| `GET /compare` | Compare page |
| `GET /api/backends` | Registered backends, labels, readiness |
| `GET /api/taxonomy` | Category/action labels and max email count |
| `GET /api/health?backend=` | Readiness for one backend |
| `POST /api/emails` | Fetch recent emails |
| `POST /api/classify` | Classify one email (optional `backend`) |

## Where to change things
- Categories and wording: `app/taxonomy.py`
- Prompt and model call (Llama): `app/classifier.py`
- BERT wrapper: `app/bert_classifier.py`
- Backend registry and factory: `app/classifier_base.py`
- Shared frontend helpers: `static/common.js`
- Sorter page: `templates/index.html`, `static/sorter.js`
- Compare page: `templates/compare.html`, `static/compare.js`
- Shared styles: `static/style.css`
- New mail source: add a file in `app/providers/` and one line in `app/providers/__init__.py`
