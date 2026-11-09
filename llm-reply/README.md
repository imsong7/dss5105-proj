# LLM Reply Drafts

用 LLM 為收到的郵件自動撰寫回覆草稿。只會產生草稿檔，**不會寄出、不會修改信箱**。

## 流程

1. 讀取收到的郵件 JSON。預設依序找 `data/received_mails.json`、`../email project/received_mails.json`；也可用 `--input` 指定。
2. 用 4 類 action 分類器篩選出 `Needs a reply` 的郵件。預設離線：有 joblib 模型時用 `--classifier ml`，否則用 `keywords`；也可用 `--classifier claude` 使用 repo 的 Claude 方法（`claude/config.yaml` 的同一套 prompt 與 labels，會呼叫 API）。
3. 呼叫 LLM 生成回覆。
4. 輸出到 `llm-reply/drafts/`：
   - `*.json`：完整記錄（原信、回覆、模型、placeholders）
   - `*.eml`：可直接匯入 Outlook / Mail 的草稿。一般 email 會用原信 `replyTo`（若有）或 `From`；Canvas 通知若沒有 `replyTo`，`To` 會留空，請手動填入對方私人 email。
   - `drafts.md`：方便快速瀏覽
   - `drafts.json`：所有草稿的合併索引（新結果覆蓋同一封信的舊草稿）

## 安裝

建議直接使用 repo 根目錄的虛擬環境（root `requirements.txt` 已含 `requests`、`PyYAML`、`scikit-learn` 等）：

```bash
cd ..                      # repo root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd llm-reply
cp .env.example .env
# 編輯 .env，填入 ANTHROPIC_API_KEY
```

預設使用 Claude：`LLM_PROVIDER=anthropic`、`LLM_MODEL=claude-sonnet-5-5`。
如要改用較便宜、適合大量生成的模型，可設 `LLM_MODEL=claude-haiku-5-5`。

4 類 action 篩選預設離線：有 joblib 模型時用 `ml`，否則用 `keywords`，不會呼叫 API。若改用 `--classifier claude`，模型會讀 `claude/config.yaml` 的 `claude.model`（預設 `claude-haiku-5-5`；可用 `CLAUDE_MODEL` 覆寫），此時一次 `Needs a reply` 最多會有兩次 API 呼叫：一次分類、一次寫草稿。

`--dry-run` 永遠離線，只印 prompt、不生成草稿；若同時指定 `--classifier claude`，會自動改用 `keywords` 預覽。

`--classifier ml` 需要 joblib 模型，預設找 `classical-ml/artifacts/required_action_model.joblib`，找不到時退回舊路徑 `../email project/ml_outputs/required_action_model.joblib`；也可用 `--ml-model` 指定。

`--classifier keywords` 不需要分類器或額外套件，會用關鍵字規則（`please reply`、`let us know`、`can you` 等）。

## 使用

```bash
# 先看會處理哪些信、送出什麼 prompt（完全離線）
python generate_replies.py --dry-run --limit 5

# 用 joblib 分類器做離線預覽
python generate_replies.py --dry-run --classifier ml --limit 5

# 產生草稿（預設只回 Needs a reply）
python generate_replies.py --limit 10

# 處理所有非 noreply 郵件
python generate_replies.py --filter all --limit 20

# 指定郵件（id 或 internetMessageId 的子字串；會略過所有篩選）
python generate_replies.py --ids "AAMkAGJk,dea82b3c"

# 只接受分類器信心值 >= 0.5 的郵件
python generate_replies.py --min-confidence 0.5

# 用本地 Ollama
LLM_PROVIDER=ollama LLM_MODEL=llama3.1 python generate_replies.py --limit 5
```

## 常用參數

| 參數 | 說明 |
| --- | --- |
| `--filter needs-reply \| all` | 篩選模式，預設 `needs-reply` |
| `--classifier keywords \| ml \| claude` | 4 類 action 分類器，預設 `ml`（有模型時）或 `keywords`（皆離線） |
| `--claude-config` | `claude/config.yaml` 路徑，預設 `../claude/config.yaml` |
| `--ml-model` | `--classifier ml` 使用的 joblib 路徑 |
| `--include-actions` | 連 `Needs an action` 一併回覆 |
| `--include-noreply` | 不跳過 noreply 寄件者 |
| `--include-broadcast` | 不跳過自動公告／群發郵件 |
| `--skip-domains` | 要跳過的寄件者網域，預設不跳過；例如 `instructure.com` |
| `--provider openai \| anthropic \| ollama` | LLM 供應商 |
| `--model` | 覆寫模型 |
| `--base-url` | 覆寫 API endpoint（OpenAI-compatible） |
| `--ids` | 指定郵件 id 子字串；有給定時會略過所有篩選 |
| `--sender-email` | 回覆者 email；預設從信件 `To` 自動判斷 |
| `--sender-name` | 回覆者姓名；預設從信件 `To` 自動判斷 |
| `--no-confirm` | 不詢問、直接使用偵測到的寄件者（適合腳本） |
| `--min-confidence` | 分類器信心門檻，預設 `0`（不啟用） |
| `--limit` | 最多處理幾封 |
| `--dry-run` | 只印 prompt、不生成草稿；永遠離線（Claude 會自動改用 keywords） |

## 注意

- `.env` 內含 API key，**不要 commit**。
- 預設只產生草稿，寄出前請人手檢查，特別是 `Placeholders:` 列出的欄位。
- 回覆身分（`From`、稱呼）優先序：`--sender-name` / `--sender-email` → `REPLY_SENDER_NAME` / `REPLY_SENDER_EMAIL` → 自動從信件 `To` 收件者判斷（即登入者信箱）。若 `To` 有多個地址而無法判斷，會要求你明確指定。
- 沒有用參數或 `.env` 指定時，互動模式下會顯示偵測到的寄件者：直接按 Enter 接受，或當場輸入新的 email／姓名更正。腳本或非互動環境不會停下來問；可用 `--no-confirm` 強制不詢問。
- 若接到 `email-sorter` 的登入流程，應該把 `authenticated_owner()`（登入者 email）傳進來，而不是在 `.env` 寫死個人資料。
- Anthropic 的 Claude Sonnet/Haiku 5.5 會拒絕 `temperature`、`top_p`、`top_k`，因此 Anthropic 請求不送 `temperature`；`--temperature` 只對 OpenAI-compatible / Ollama 生效。
- 預設不跳過 Canvas／`instructure.com`，避免漏掉講師需要回覆的通知；若不想處理 Canvas 通知，可加 `--skip-domains instructure.com`。
- Canvas 通知的寄件者通常是 `notifications@instructure.com`，不是講師本人；若信中沒有 `replyTo`，`.eml` 的 `To` 會留空並在 `drafts.md` 標記 `[fill in recipient email]`，請手動填入講師的私人 email 再寄出。
- 若顯示 `nothing selected; skipped: ...`，代表郵件被 noreply、網域、broadcast、分類器或信心門檻濾掉；用 `--filter all` 或 `--include-broadcast`、`--skip-domains ""` 除錯。
- `drafts.json` / `drafts.md` 會與舊草稿合併（同一封信用新結果覆蓋），不會再整批覆蓋。
