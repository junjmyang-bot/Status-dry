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

## Streamlit launcher
This repo now includes a minimal Streamlit launcher:

- main file: `streamlit_app.py`
- python deps: `requirements.txt`
- system package for runtime: `packages.txt`

If you connect this repo to Streamlit:

1. set app entrypoint to `streamlit_app.py`
2. add these secrets in Streamlit:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `SHEETS_WEBHOOK_URL`
3. keep using `src/server.js` as the real dry app backend

Note:
- current UI is still a Node app
- Streamlit here is a launcher/diagnostic wrapper, not a rewrite of the dry app UI

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
