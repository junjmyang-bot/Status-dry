const { readJson, writeJson } = require('../lib/fileStore');
const config = require('../config');

const LOCK_FILE = config.storage.teamLockFile || config.storage.pendingQueueFile.replace('pending-queue.json', 'team-locks.json');

function loadLocks() {
  return readJson(LOCK_FILE, {});
}

function saveLocks(locks) {
  writeJson(LOCK_FILE, locks);
}

function key(teamId, workDate) {
  return `${teamId}__${workDate}`;
}

function openTeam(teamId, workDate, lockOwner) {
  const locks = loadLocks();
  const k = key(teamId, workDate);
  const existing = locks[k];

  if (!existing) {
    locks[k] = {
      teamId,
      workDate,
      lockOwner,
      lockToken: `${k}__${Date.now()}`,
      version: 1,
      updated_at: new Date().toISOString()
    };
    saveLocks(locks);
    return locks[k];
  }

  if (existing.lockOwner === lockOwner) {
    return existing;
  }

  throw new Error(`Team lock is owned by ${existing.lockOwner}. Use Take Over Team.`);
}

function takeOverTeam(teamId, workDate, lockOwner) {
  const locks = loadLocks();
  const k = key(teamId, workDate);
  const existing = locks[k] || { version: 0 };

  locks[k] = {
    teamId,
    workDate,
    lockOwner,
    lockToken: `${k}__${Date.now()}`,
    version: Number(existing.version || 0) + 1,
    updated_at: new Date().toISOString()
  };

  saveLocks(locks);
  return locks[k];
}

function assertWriteAllowed({ teamId, workDate, lockToken, expectedVersion, lockOwner }) {
  const locks = loadLocks();
  const current = locks[key(teamId, workDate)];

  if (!current) {
    throw new Error('Team is not open. Open Team first.');
  }

  // Same owner should not fail from stale token in reopened session.
  if (current.lockOwner !== lockOwner && current.lockToken !== lockToken) {
    throw new Error('Lock conflict: token mismatch. Use Take Over Team.');
  }

  if (Number(expectedVersion) !== Number(current.version)) {
    throw new Error(`Version conflict: expected ${expectedVersion}, current ${current.version}`);
  }

  return current;
}

module.exports = {
  openTeam,
  takeOverTeam,
  assertWriteAllowed
};
