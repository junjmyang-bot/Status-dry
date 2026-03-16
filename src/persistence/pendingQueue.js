const { readJson, writeJson } = require('../lib/fileStore');
const config = require('../config');

function loadQueue() {
  const items = readJson(config.storage.pendingQueueFile, []);
  if (!Array.isArray(items)) return [];
  return items.filter((x) => x && x.id && x.payload && x.teamId && x.workDate && x.idempotencyKey);
}

function saveQueue(items) {
  writeJson(config.storage.pendingQueueFile, items);
}

function enqueue(item) {
  const items = loadQueue();
  items.push(item);
  saveQueue(items);
  return item;
}

function updateById(id, patch) {
  const items = loadQueue();
  const idx = items.findIndex((x) => x.id === id);
  if (idx < 0) return null;
  items[idx] = { ...items[idx], ...patch, updated_at: new Date().toISOString() };
  saveQueue(items);
  return items[idx];
}

function removeById(id) {
  const items = loadQueue();
  const next = items.filter((x) => x.id !== id);
  saveQueue(next);
}

module.exports = {
  loadQueue,
  enqueue,
  updateById,
  removeById
};
