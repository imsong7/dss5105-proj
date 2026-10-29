# Inbox Sorter · Version 1 (pasted token + Claude)

Labels every new Outlook email with one **topic** (Category A) and one **action** (Category B), and shows the results in a local dashboard. It reads your mail with an access token you copy from **Microsoft Graph Explorer**, so no Azure app registration is needed, and **Claude** does the classification.

- **Category A (topic):** FoS General, Career, Medical, Promotions, Canvas, Others
- **Category B (action):** Needs a reply, Needs an action, Reminder, Further review, No action needed

It is read-only: it only sends GET requests to Microsoft Graph and never changes, moves, flags or sends mail.

## What to know about the pasted token

- It lasts **about an hour** and can't be renewed automatically. When it expires, paste a fresh one. The dashboard shows how long the current one has left.
- Nothing is lost while it's expired: the next sync catches up on everything that arrived in the meantime.
- It can read your mail while valid. Keep it private. It's stored only in `data/graph_token.txt` on your machine (gitignored) and is never logged.
- Its permissions are whatever you consented to in Graph Explorer. Only consent to **Mail.Read** for this project.
- Your university blocked app registration; check that using your own Graph Explorer token for a personal tool is acceptable under its IT policy.

## Project layout

```
config.yaml           labels, definitions, Claude model, targets (edit this, not the code)
.env.example          secrets template: copy to .env
src/
  graph_token.py      save/load/inspect the pasted token (expiry, scopes)
  graph.py            read-only Graph calls
  preprocess.py       HTML to text, quote stripping
  llm.py              Claude classifier with validated JSON output
  rules.py            no-reply guardrail; optional free shortcuts
  pipeline.py         shortcuts -> Claude -> guardrails -> Further review
  sync.py             one sync: read new mail, classify, store
  store.py            SQLite: metadata, labels, corrections (never email bodies)
  worker.py           optional background loop
  dataset.py          export emails for your accuracy test set
  evaluate.py         Claude's accuracy against your labels
app/
  dashboard.py        paste token, Sync now, browse, correct
  label_tool.py       label a test set by hand
tests/test_system.py  offline tests (no token or API key needed)
```

This project is also available as the **Claude** backend in
`email-sorter/`, and is benchmarked against the other three methods:

```bash
# from the repo root
python email-sorter/run.py --backend claude      # app backend
python evaluation/performance.py --model all     # llama + bert + ml + claude
python evaluation/quality.py --model all         # accuracy and macro F1
```

`evaluation/inbox_sorter.py` loads the package from here under an alias (its
`src`/`app` names would otherwise shadow the other projects) and maps the
labels above onto the email-sorter taxonomy.

## Setup

1. **Install Python 3.11+**, then in this folder:
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   pytest -q                          # 21 passed, no accounts needed
   ```
2. **Get a Claude API key.** In the Claude Console, add billing, set a monthly spend limit, and create a key under API Keys.
3. **Configure.** `cp .env.example .env` (Windows: `copy .env.example .env`) and set `ANTHROPIC_API_KEY`. The model is `claude.model` in `config.yaml` (default `claude-haiku-5-5`).
4. **Start the dashboard:** `streamlit run app/dashboard.py`

### Thinking tokens

Newer Claude models think before they answer, and those thinking tokens are
billed against `claude.max_tokens`. With a small budget the whole answer can be
spent on thinking, leaving no JSON behind -- the email then falls back to
"Further review" for no visible reason.

So `config.yaml` keeps `claude.max_tokens: 512` and sets `claude.thinking:
disabled` (labelling does not need reasoning). Change it to `enabled` (with
`claude.thinking_budget_tokens`) or `auto` if you want the model to reason.
`max_tokens` must be larger than the thinking budget.

## Getting a Graph token

1. Open Microsoft Graph Explorer and sign in with your university account.
2. Open **Modify permissions** (or the permissions panel), find **Mail.Read** and press **Consent**. One time only. If this needs admin approval, the pasted-token approach won't work either; ask IT.
3. Run `GET https://graph.microsoft.com/v1.0/me/messages?$top=1` to confirm it returns an email.
4. Open the **Access token** tab and copy the token.
5. Paste it into the dashboard sidebar and press **Save token**. Or in a terminal: `python -m src.graph_token`.

## Daily use

- In the dashboard, press **Sync now**. It reads mail since the last sync (the first time, the last 7 days), sends each email to Claude, and shows the labels.
- Each sync handles up to 200 emails (`worker.max_per_sync`) to keep costs predictable; press Sync again if more are waiting.
- Click **Open in Outlook** to read an email. The **Why** column shows Claude's one-line reason.
- Fix a wrong label and press **Save corrections**. The **Health** tab summarises your corrections; use them to sharpen definitions or add `examples` in `config.yaml`.
- **Optional automatic syncing:** in a second terminal, `python -m src.worker` syncs every 2 minutes while the token is valid, then waits until you paste a new one.

## Measuring accuracy (recommended before relying on it)

```bash
python -m src.dataset export --n 300      # needs a valid token
streamlit run app/label_tool.py           # label them yourself, without seeing Claude's answers
python -m src.evaluate                    # Claude vs. your labels -> reports/
```

The report shows PASS/FAIL against `targets:` in `config.yaml`, confusion matrices, and every disagreement with Claude's reason. Fix definitions, add examples, re-run (only new or changed results cost API calls). For a consistency check, re-label 100 in the label tool's **Second-pass mode** and run `python -m src.dataset kappa`.

### Definitions must match the shared review rubric

When this sorter is compared with the other three methods, it is scored against
the shared review labels (`data/labels.csv`). The action definitions in
`config.yaml` are aligned with that rubric on purpose: an announcement of a
talk, workshop or event asks for nothing, so it is `No action needed` and not
`Reminder`. On the 134 action-usable emails that wording is worth **+10
accuracy points** for Claude (0.784 -> 0.888). The per-class numbers are kept in
`evaluation/results/rubric_alignment.csv`.

## Cost control

- Only text up to `preprocess.max_chars` (4,000 characters) is sent per email.
- `worker.max_per_sync` caps calls per sync; `backfill_days` limits the first sync.
- Optional free shortcuts (`rules.use_shortcuts: true`) skip Claude for Canvas notifications and obvious promotions. Turn them on only after `evaluate` shows they're accurate on your mail.
- Set a monthly spend limit in the Claude Console.

## Data handling

- The database stores sender, subject, received time, Outlook link, labels and Claude's short reason. **Email bodies are never stored.**
- Email text is sent to the Claude API for classification. Check this is acceptable for your mail.
- Records older than `worker.retention_days` (90) are deleted.
- `data/raw.jsonl` (your test set) contains email text; delete it when you no longer need it.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Token expired" | Copy a fresh token from Graph Explorer and paste it |
| "token has no Mail.Read permission" | Consent to Mail.Read in Graph Explorer, then copy a new token |
| "ANTHROPIC_API_KEY is missing" | Add it to `.env` and restart the dashboard |
| `AuthenticationError` from Claude | The API key is wrong or revoked |
| Many emails in Further review | Claude is unsure: sharpen definitions or add examples, or lower `claude.min_confidence` |
| Dashboard empty | Press Sync now; check shadow mode is off |
