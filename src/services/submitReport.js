const crypto = require('crypto');

const config = require('../config');
const { buildTelegramMainMessage, buildTelegramUpdateReply } = require('../formatters/telegramFormatter');
const { buildSheetsRows } = require('../formatters/sheetsRowFormatter');
const telegram = require('../integrations/telegramGateway');
const sheets = require('../integrations/sheetsGateway');
const queue = require('../persistence/pendingQueue');
const roots = require('../persistence/rootMessageStore');
const locks = require('../persistence/teamLockStore');
const timeIntegrity = require('../persistence/timeIntegrityStore');

function makeSubmissionId() {
  return crypto.randomUUID();
}

function buildLifecycleKey({ teamId, workDate, version }) {
  return `dry-${workDate}-${teamId}-v${version}`;
}

async function upsertTelegramMainMessage(text, existing) {
  const oldRootId = existing?.root_message_id || existing?.main_message_id || null;
  if (oldRootId) {
    try {
      const edited = await telegram.editMessage(oldRootId, { text });
      return edited.message_id;
    } catch (_) {}
  }

  const created = await telegram.sendMessage({ text });
  return created.message_id;
}

async function attemptSubmission(item) {
  const { payload, teamId, workDate, idempotencyKey } = item;

  const mainMessageText = buildTelegramMainMessage(payload);
  const replyText = buildTelegramUpdateReply(payload);
  const existingRoot = roots.getRoot(teamId, workDate);
  const rootMessageId = await upsertTelegramMainMessage(mainMessageText, existingRoot);
  const replyMessage = await telegram.sendMessage({
    text: replyText,
    replyToMessageId: rootMessageId
  });

  roots.setRoot(teamId, workDate, {
    root_message_id: rootMessageId,
    main_message_id: rootMessageId,
    part_message_ids: [rootMessageId],
    last_reply_message_id: replyMessage.message_id,
    idempotency_key: idempotencyKey,
    updated_at: new Date().toISOString()
  });

  const rows = buildSheetsRows(payload, { idempotencyKey });

  try {
    await sheets.appendRows(rows);
    return { status: 'success', sheets_ok: true, telegram_ok: true };
  } catch (err) {
    if (!config.policies.allowTelegramWhenSheetsFails) throw err;
    return { status: 'partial_success', sheets_ok: false, telegram_ok: true, error: err.message };
  }
}

async function submitReport({ payload, teamId, workDate, lockToken, lockOwner, expectedVersion }) {
  const lock = locks.assertWriteAllowed({ teamId, workDate, lockToken, expectedVersion, lockOwner });
  const guarded = timeIntegrity.validateAndPreparePayload({ teamId, workDate, payload });
  const id = makeSubmissionId();
  const idempotencyKey = buildLifecycleKey({ teamId, workDate, version: lock.version });

  const item = {
    id,
    teamId,
    workDate,
    idempotencyKey,
    payload: guarded.payload,
    status: 'pending',
    retry_count: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  };

  queue.enqueue(item);
  queue.updateById(id, { status: 'sending' });

  try {
    const result = await attemptSubmission(item);

    if (result.status === 'success') {
      timeIntegrity.commitFromPayload({ teamId, workDate, payload: item.payload });
      queue.removeById(id);
      return { id, status: 'success', idempotencyKey, message: 'Telegram + Sheets success' };
    }

    timeIntegrity.commitFromPayload({ teamId, workDate, payload: item.payload });
    queue.updateById(id, {
      status: 'failed',
      retry_count: item.retry_count + 1,
      last_error: `Sheets backup failed: ${result.error}`
    });

    return { id, status: 'failed', idempotencyKey, message: 'Telegram sent, Sheets failed. Retry available.' };
  } catch (err) {
    queue.updateById(id, {
      status: 'failed',
      retry_count: item.retry_count + 1,
      last_error: err.message
    });

    return { id, status: 'failed', idempotencyKey, message: err.message };
  }
}

async function retryPending() {
  const items = queue.loadQueue().filter((x) => x.status === 'failed' || x.status === 'pending');
  const results = [];

  for (const item of items) {
    queue.updateById(item.id, { status: 'sending' });
    try {
      const result = await attemptSubmission(item);
      if (result.status === 'success') {
        timeIntegrity.commitFromPayload({ teamId: item.teamId, workDate: item.workDate, payload: item.payload });
        queue.removeById(item.id);
        results.push({ id: item.id, status: 'success' });
      } else {
        timeIntegrity.commitFromPayload({ teamId: item.teamId, workDate: item.workDate, payload: item.payload });
        queue.updateById(item.id, {
          status: 'failed',
          retry_count: Number(item.retry_count || 0) + 1,
          last_error: `Sheets backup failed: ${result.error}`
        });
        results.push({ id: item.id, status: 'failed', reason: 'sheets_failed' });
      }
    } catch (err) {
      queue.updateById(item.id, {
        status: 'failed',
        retry_count: Number(item.retry_count || 0) + 1,
        last_error: err.message
      });
      results.push({ id: item.id, status: 'failed', reason: err.message });
    }
  }

  return results;
}

module.exports = {
  submitReport,
  retryPending,
  buildLifecycleKey,
  openTeam: locks.openTeam,
  takeOverTeam: locks.takeOverTeam
};
