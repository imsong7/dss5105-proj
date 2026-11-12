# Inbox Sorter · Content-Only Priority Version

Labels every new Outlook email with one **topic** (Category A), one **action** (Category B) and a **priority from 1 to 5 stars**, and shows the results in a local dashboard.

**How this version differs from the main version:** the stars are based **only on the email's content**: what is at stake, how soon, and who it is for. The topic and action labels play no part in the stars. Everything else is the same: classification, the dashboard, token handling and data handling. `python -m src.compare` scores both priority models on your own labelled emails, so you can see which one matches you better. It reads your mail with an access token you copy from **Microsoft Graph Explorer**, so no Azure app registration is needed, and **Claude** does the classification.

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
  priority.py         1-5 star priority from Claude's factor scores (content only, or combined)
  compare.py          scores both priority models on your labelled emails, no API calls
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

## Setup

1. **Install Python 3.11+**, then in this folder:
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   pytest -q                          # 111 passed, no accounts needed
   ```
2. **Get a Claude API key.** In the Claude Console, add billing, set a monthly spend limit, and create a key under API Keys.
3. **Configure.** `cp .env.example .env` (Windows: `copy .env.example .env`) and set `ANTHROPIC_API_KEY`. The model is `claude.model` in `config.yaml` (default `claude-haiku-5-5`).
4. **Start the dashboard:** `streamlit run app/dashboard.py`

## Getting a Graph token

1. Open Microsoft Graph Explorer and sign in with your university account.
2. Open **Modify permissions** (or the permissions panel), find **Mail.Read** and press **Consent**. One time only. If this needs admin approval, the pasted-token approach won't work either; ask IT.
3. Run `GET https://graph.microsoft.com/v1.0/me/messages?$top=1` to confirm it returns an email.
4. Open the **Access token** tab and copy the token.
5. Paste it into the dashboard sidebar and press **Save token**. Or in a terminal: `python -m src.graph_token`.

## Daily use

- In the dashboard, press **Sync now**. It reads mail since the last sync (the first time, the last 7 days), sends each email to Claude, and shows the labels.
- Each sync handles up to 200 emails (`worker.max_per_sync`) to keep costs predictable; press Sync again if more are waiting.
- Emails are sorted by **priority** (switch to newest or due date in the sidebar), with a minimum-stars filter. ⚠ marks possible phishing.
- Click **Open in Outlook** to read an email. **Due** shows the deadline; **Why** shows the key point and factor scores (C, U, R).
- Fix a wrong label or star rating and press **Save corrections**. The **Health** tab summarises your corrections; use them to sharpen definitions or add `examples` in `config.yaml`.
- **Optional automatic syncing:** in a second terminal, `python -m src.worker` syncs every 2 minutes while the token is valid, then waits until you paste a new one.

## Priority ranking (1 to 5 stars, content only)

In the same API call that assigns the labels, Claude scores three content factors from 0 to 3:

- **Consequence**: what happens if the email is ignored, from nothing (0) to a financial penalty, losing a place, health or official standing (3).
- **Urgency**: 3 if due within 2 days, 2 within a week, 1 within a month. Counted from the day the email **arrived**, using the deadline Claude finds.
- **Relevance**: mass marketing (0) through to you personally (3).

It also returns the deadline, a phishing flag and a short key point. The code turns the factors into stars, ignoring the topic and action:

```
score = 2.0 x consequence + 1.5 x urgency + 1.0 x relevance      (0 to 13.5)
11.5+ -> 5 stars | 9+ -> 4 | 6+ -> 3 | 3+ -> 2 | below -> 1
```

Then guardrails, all based on content too. The floor comes first: something serious that's due within a week gets at least 4 stars. The caps come last and always win: mass marketing (relevance 0) at most 3 stars, and likely phishing at most 2, with a warning. There are no topic or action caps, so a Promotions email can rate above 3 if Claude reads it as personal and pressing.

- **Stars are fixed when the email arrives.** You can adjust any rating in the dashboard's Priority column.
- All settings are in `config.yaml` under `priority.content_only`. Changing them costs no API calls, because `python -m src.evaluate` re-scores cached results.
- `priority.model` switches between `content_only` (this version) and `combined` (the main version's formula, also kept in the config).
- **Emails without stars** (synced before priority existed, or whose classification failed) can be filled in with `python -m src.sync --reclassify --days 14`. That costs one API call per email and keeps your labels and star adjustments.

## Comparing with the main version's priority model

```bash
python -m src.evaluate      # classify your hand-labelled test set once (API calls, cached)
python -m src.compare       # score it with both models (no API calls) -> reports/compare_*.md
```

The report compares both models against your own star ratings: within one star, critical recall, over-ranking, rank correlation, and how many Promotions rated above 3 stars. It also gives average stars per topic, and lists every email where the two models differ, showing which one was closer to your rating.

## How Claude's answers are checked

Claude answers through a structured tool call whose schema lists your exact labels, so the reply arrives as data rather than free text. The answer is still checked against `config.yaml`. Small differences, such as other capitals, spacing, a missing "a" or "an", or a plural, are accepted; anything else is rejected. A rejected answer is asked again once (`claude.retries_on_bad_answer`). If it still fails, the email goes to Further review and the reason is shown in the Why column and logged to `data/claude_failures.jsonl` (Claude's reply only, never the email).

## Measuring accuracy (recommended before relying on it)

```bash
python -m src.dataset export --n 300      # needs a valid token
streamlit run app/label_tool.py           # label topic, action and stars yourself, without seeing Claude's answers
python -m src.evaluate                    # Claude vs. your labels -> reports/
```

The report shows PASS/FAIL against `targets:` in `config.yaml`, confusion matrices, and every disagreement with Claude's reason. For priority it shows your stars against the system's stars as a grid, plus four metrics: within one star (target 90%), critical recall (your 5-star emails rated 4 or 5, target 95%), over-ranking (your 1–2 star emails rated 4 or 5, at most 5%), and rank correlation. It also lists every email where the two differ by 2 or more stars. Fix definitions, add examples, re-run (only new or changed results cost API calls). For a consistency check, re-label 100 in the label tool's **Second-pass mode** and run `python -m src.dataset kappa`.

## Cost control

- Only text up to `preprocess.max_chars` (4,000 characters) is sent per email.
- `worker.max_per_sync` caps calls per sync; `backfill_days` limits the first sync.
- Optional free shortcuts (`rules.use_shortcuts: true`) skip Claude for Canvas notifications and obvious promotions. Turn them on only after `evaluate` shows they're accurate on your mail.
- Set a monthly spend limit in the Claude Console.

## Data handling

- The database stores sender, subject, received time, Outlook link, labels, stars, factor scores, deadline, and Claude's short reason and key point. **Email bodies are never stored.**
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
| Why column says "classification failed: ..." | The text after the colon says what was wrong with Claude's answer. The Health tab lists recent failures (also in `data/claude_failures.jsonl`). Retry them with `python -m src.sync --reclassify --days 14` |
| Emails without stars | Synced before priority ranking existed, or Claude's priority scores were invalid. `python -m src.sync --reclassify --days 14` fills them in |
| Dashboard empty | Press Sync now; check shadow mode is off |
