# Claude backend

This folder is the Claude method used by `email-sorter` as the `claude` and
`hybrid_claude` backends. It keeps the original pipeline:

```
sender rules -> Claude API -> guardrails -> fallback
```

The standalone Streamlit dashboard, Graph token fetcher, sync worker and
dataset/evaluation tools were removed. Use `email-sorter` for the UI; Claude
results are collected in [`../MODEL_COMPARISON.md`](../MODEL_COMPARISON.md).

## Files

| Path | Purpose |
|---|---|
| `config.yaml` | Topics, actions, Claude model, sender rules, fallback |
| `.env` | `ANTHROPIC_API_KEY` (local, gitignored) |
| `src/config.py` | Load `config.yaml` and `.env` |
| `src/llm.py` | Claude call, JSON parsing, usage diagnostics |
| `src/preprocess.py` | HTML to text, quote stripping, rule features |
| `src/rules.py` | Sender/thread shortcuts and the no-reply guardrail |
| `src/pipeline.py` | rules -> Claude -> guardrails -> fallback |
| `tests/test_system.py` | Offline tests; no API key needed |

## Setup

From `claude/` (the root requirements file covers all methods):

```bash
pip install -r ../requirements.txt
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

## Use

From the repo root:

```bash
python email-sorter/run.py --backend claude
python email-sorter/run.py --backend hybrid_claude   # ML category + Claude action
```

`claude` uses Claude for both labels. `hybrid_claude` uses the classical-ML
category model and Claude for the action.

## Tests

```bash
cd claude
pytest -q
```
