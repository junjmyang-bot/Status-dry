const fs = require('fs');
const path = require('path');

const ROOT_DIR = path.resolve(__dirname, '..');

function loadDotEnv(rootDir) {
  const envPath = path.join(rootDir, '.env');
  if (!fs.existsSync(envPath)) return;

  const raw = fs.readFileSync(envPath, 'utf8');
  const lines = raw.split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const idx = trimmed.indexOf('=');
    if (idx < 0) continue;
    const key = trimmed.slice(0, idx).trim();
    const value = trimmed.slice(idx + 1).trim();
    if (!key) continue;
    if (process.env[key] === undefined || process.env[key] === '') {
      process.env[key] = value;
    }
  }
}

loadDotEnv(ROOT_DIR);

module.exports = {
  timezone: process.env.APP_TIMEZONE || 'Asia/Jakarta',
  telegram: {
    botToken: process.env.TELEGRAM_BOT_TOKEN || '',
    chatId: process.env.TELEGRAM_CHAT_ID || ''
  },
  sheets: {
    webhookUrl: process.env.SHEETS_WEBHOOK_URL || ''
  },
  storage: {
    pendingQueueFile: process.env.PENDING_QUEUE_FILE || path.join(ROOT_DIR, 'storage', 'pending-queue.json'),
    rootMessageFile: process.env.ROOT_MESSAGE_FILE || path.join(ROOT_DIR, 'storage', 'root-messages.json'),
    teamLockFile: process.env.TEAM_LOCK_FILE || path.join(ROOT_DIR, 'storage', 'team-locks.json'),
    timeIntegrityFile: process.env.TIME_INTEGRITY_FILE || path.join(ROOT_DIR, 'storage', 'time-integrity.json')
  },
  policies: {
    allowTelegramWhenSheetsFails: true
  }
};
