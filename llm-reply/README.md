# LLM Reply Drafts

Generate reply drafts for received emails with an LLM. This tool only creates draft files; **it does not send emails or modify the mailbox**.

## Flow

1. Read the received email JSON. By default, it checks `data/received_mails.json` and then `../email project/received_mails.json`; use `--input` to provide another path.
2. Use a 4-class action classifier to select emails labelled `Needs a reply`. This is offline by default: it uses `--classifier ml` when a joblib model is available, otherwise it uses `keywords`. You can also use `--classifier claude` to use the repository's Claude method (the same prompt and labels from `claude/config.yaml`, which calls the API).
3. Call the LLM to generate replies. If the prompt, provider, and model for an email are unchanged, the existing draft in `drafts.json` is reused by default without calling the API.
4. Write output to `llm-reply/drafts/`:
   - `*.json`: full record (original email, reply, model, placeholders, `guardrail_issues`)
   - `*.eml`: draft that can be imported directly into Outlook / Mail. For normal emails, the tool uses the original `replyTo` if present, otherwise `From`. For Canvas notifications without `replyTo`, `To` is left blank; fill in the recipient's private email manually.
   - `drafts.md`: quick overview (including guardrail warnings)
   - `drafts.json`: merged index of all drafts (new results replace older drafts for the same email and record `generated_count` / `cached_count`)

## Installation

Use the virtual environment at the repository root (the root `requirements.txt` includes `requests`, `PyYAML`, `scikit-learn`, and others):

```bash
cd ..                      # repo root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd llm-reply
cp .env.example .env
# Edit .env and add ANTHROPIC_API_KEY
```

Claude is used by default: `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-5-5`.
To use a cheaper model better suited to high-volume generation, set `LLM_MODEL=claude-haiku-5-5`.

The 4-class action filter is offline by default: it uses `ml` when a joblib model is available, otherwise `keywords`, and does not call the API. If you use `--classifier claude`, the model reads `claude.model` from `claude/config.yaml` (default `claude-haiku-5-5`; override with `CLAUDE_MODEL`). In that case, one `Needs a reply` email can use up to two API calls: one for classification and one for drafting.

`--dry-run` is always offline and only prints the prompt without generating drafts. If you also use `--classifier claude`, it automatically switches to `keywords` for the preview.

Drafts are cached by default: if the prompt, provider, and model for an email are unchanged, the existing draft in `drafts.json` is reused and the API is not called. Add `--force` to regenerate.

`--classifier ml` requires a joblib model. By default, it looks for `classical-ml/artifacts/required_action_model.joblib`, then falls back to the old path `../email project/ml_outputs/required_action_model.joblib`; you can also provide a path with `--ml-model`.

`--classifier keywords` does not require a classifier or extra dependencies. It uses keyword rules such as `please reply`, `let us know`, and `can you`.

## Usage

```bash
# Preview which emails will be processed and what prompt is sent (fully offline)
python generate_replies.py --dry-run --limit 5

# Offline preview using the joblib classifier
python generate_replies.py --dry-run --classifier ml --limit 5

# Generate drafts (only Needs a reply by default)
python generate_replies.py --limit 10

# Process all non-noreply emails
python generate_replies.py --filter all --limit 20

# Select emails by id or a substring of internetMessageId (bypasses all filters)
python generate_replies.py --ids "AAMkAGJk,dea82b3c"

# Only accept emails with classifier confidence >= 0.5
python generate_replies.py --min-confidence 0.5

# Use local Ollama
LLM_PROVIDER=ollama LLM_MODEL=llama3.1 python generate_replies.py --limit 5
```

## Common Options

| Option | Description |
| --- | --- |
| `--filter needs-reply \| all` | Filter mode; default `needs-reply` |
| `--classifier keywords \| ml \| claude` | 4-class action classifier; default `ml` when a model is available, otherwise `keywords` (both offline) |
| `--claude-config` | Path to `claude/config.yaml`; default `../claude/config.yaml` |
| `--ml-model` | Joblib path used by `--classifier ml` |
| `--include-actions` | Also reply to `Needs an action` emails |
| `--include-noreply` | Do not skip noreply senders |
| `--include-broadcast` | Do not skip automated announcements or bulk emails |
| `--skip-domains` | Sender domains to skip; none by default, for example `instructure.com` |
| `--provider openai \| anthropic \| ollama` | LLM provider |
| `--model` | Override the model |
| `--base-url` | Override the API endpoint (OpenAI-compatible) |
| `--ids` | Select emails by id substring; all filters are bypassed when provided |
| `--sender-email` | Sender email for replies; detected automatically from the email's `To` field by default |
| `--sender-name` | Sender name for replies; detected automatically from the email's `To` field by default |
| `--no-confirm` | Do not prompt; use the detected sender directly (useful for scripts) |
| `--min-confidence` | Classifier confidence threshold; default `0` (disabled) |
| `--limit` | Maximum number of emails to process |
| `--output` | Draft output directory; default `llm-reply/drafts/` |
| `--force` | Regenerate drafts with the LLM even when a cached draft exists |
| `--dry-run` | Only print prompts and do not generate drafts; always offline (Claude falls back to keywords) |

## Offline Evaluation

`eval_cases.json` contains 8 scenarios (consultation, extension, group scheduling, event RSVP, account access, feedback, deadline clarification, and rescheduling). Each case includes an `ideal_reply` and scoring rules. `eval_replies.py` only reads drafts and does not call the API.

```bash
# Validate the scoring rules themselves (using each case's ideal_reply)
python eval_replies.py --use-ideal

# Evaluate generated drafts
python eval_replies.py --drafts drafts/drafts.json
```

To generate model drafts for these 8 cases, first write them to a separate directory with `--input eval_cases.json --ids "eval-"`. This step calls the LLM API:

```bash
python generate_replies.py --input eval_cases.json --ids "eval-" --output drafts-eval
python eval_replies.py --drafts drafts-eval/drafts.json
```

## Notes

- `.env` contains the API key; **do not commit it**.
- The tool only generates drafts. Review them manually before sending, especially fields listed under `Placeholders:`.
- Sender identity (`From` and form of address) precedence: `--sender-name` / `--sender-email` -> `REPLY_SENDER_NAME` / `REPLY_SENDER_EMAIL` -> automatic detection from the email's `To` recipient (the signed-in mailbox). If `To` contains multiple addresses and the owner cannot be determined, you must specify it explicitly.
- When no option or `.env` value is provided, interactive mode shows the detected sender: press Enter to accept, or type a new email / name to correct it. Scripts and non-interactive environments do not pause for input; use `--no-confirm` to suppress the prompt.
- If integrated with the `email-sorter` login flow, pass in `authenticated_owner()` (the signed-in user's email) instead of hard-coding personal details in `.env`.
- Anthropic Claude Sonnet/Haiku 5.5 rejects `temperature`, `top_p`, and `top_k`, so Anthropic requests do not send `temperature`; `--temperature` only applies to OpenAI-compatible providers and Ollama.
- Canvas / `instructure.com` is not skipped by default, so notifications that require a reply from an instructor are not missed. To skip Canvas notifications, add `--skip-domains instructure.com`.
- Canvas notifications usually come from `notifications@instructure.com`, not the instructor. If the email has no `replyTo`, the `.eml` `To` field is left blank and `drafts.md` marks `[fill in recipient email]`; fill in the instructor's private email before sending.
- If you see `nothing selected; skipped: ...`, the emails were filtered out by noreply, domain, broadcast, classifier, or confidence rules. Use `--filter all`, `--include-broadcast`, or `--skip-domains ""` to debug.
- Each draft includes `guardrail_issues`, which flags raw email addresses, AI/assistant wording, and duplicate or unlisted placeholders. When there are issues, `drafts.md` shows `Guardrail:`; fix them before sending.
- `drafts.json` / `drafts.md` are merged with older drafts (new results replace older drafts for the same email) instead of replacing the whole batch. Identical prompt / provider / model combinations reuse the cache; add `--force` to regenerate.
