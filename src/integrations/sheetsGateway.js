const config = require('../config');

async function appendRows(rows) {
  if (!config.sheets.webhookUrl) throw new Error('Missing SHEETS_WEBHOOK_URL');

  const resp = await fetch(config.sheets.webhookUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows })
  });

  const text = await resp.text();
  if (!resp.ok) {
    throw new Error(`Sheets append failed: HTTP ${resp.status} ${text}`);
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (_) {
    parsed = { ok: true, raw: text };
  }

  if (parsed.ok === false) {
    throw new Error(`Sheets append failed: ${parsed.error || 'unknown error'}`);
  }

  return parsed;
}

module.exports = {
  appendRows
};
