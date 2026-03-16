# Dry Status Ops Flow (Telegram + Sheets)

## What is implemented
- Telegram formatter with scan-friendly sections and safe rollover.
- Sheets row formatter with per-slot dedupe key.
- Submit orchestrator with:
  - edit-first Telegram policy (fallback to send new)
  - mandatory Sheets backup attempt
  - non-blocking Sheets failure policy + visible failed status
  - persistent pending queue for retry
- Team lock model:
  - Open Team
  - Take Over Team
  - token + version check on submit
  - same lock owner does not get false conflict

## Env
Copy `.env.example` values into your runtime env.

Required:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SHEETS_WEBHOOK_URL`

Optional:
- `APP_TIMEZONE` (default `Asia/Jakarta`)

## Streamlit operator deployment
The operator-facing app is now `streamlit_app.py`.

Deployment target:
- Streamlit Community Cloud

Required files already included:
- `streamlit_app.py`
- `requirements.txt`
- `packages.txt`
- `.streamlit/config.toml`

How it works:
- Streamlit is the main operator UI
- `streamlit_app.py` starts `src/server.js` internally on localhost
- operators do not open a separate localhost page; they work directly inside Streamlit

Streamlit app settings:
- Main file path: `streamlit_app.py`
- Python version: `3.11` or newer

Required Streamlit secrets:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SHEETS_WEBHOOK_URL`

Optional secret:
- `APP_TIMEZONE=Asia/Jakarta`

Notes:
- `packages.txt` installs `nodejs` so Streamlit can start the internal backend
- the backend remains local to the Streamlit runtime and is not an operator-facing URL
- draft data is stored in `storage/streamlit-operator-draft.json`

## Optional direct Node deployment
This repo still includes direct Node deployment files if needed for backend-only testing or alternative hosting:

- `package.json`
- `render.yaml`

## CLI usage
### 1) Open Team
```bash
node src/index.js open dry-team-1 2026-03-05 aris
```

### 2) Submit report
```bash
node src/index.js submit report.sample.json dry-team-1 2026-03-05 aris <lockToken> 1
```

If same `lockOwner` is submitting and token is temporarily unavailable, owner-check still allows submit.

### 3) Take Over Team
```bash
node src/index.js takeover dry-team-1 2026-03-05 fauzan
```

### 4) Retry failed/pending queue
```bash
node src/index.js retry
```

## Storage files
- `storage/pending-queue.json`
- `storage/root-messages.json`
- `storage/team-locks.json`

## Integration notes
- `src/services/submitReport.js` is the entry point to wire into UI/backend.
- `src/formatters/telegramFormatter.js` outputs split-safe message parts.
- `src/formatters/sheetsRowFormatter.js` outputs row objects with dedupe keys.
