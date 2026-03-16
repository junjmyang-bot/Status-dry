const { readJson, writeJson } = require('../lib/fileStore');
const config = require('../config');

const FIELD_PAIRS = [
  { dateKey: 'tgl_masuk', timeKey: 'jam_masuk', label: 'Jam Masuk' },
  { dateKey: 'tgl_defros', timeKey: 'jam_defros', label: 'Jam Defrost' },
  { dateKey: 'tgl_selesai_dry', timeKey: 'jam_selesai_dry', label: 'Jam Selesai Dry' },
  { dateKey: 'tgl_turun_packing', timeKey: 'jam_turun_packing', label: 'Jam Turun Packing' }
];

function key(teamId, workDate) {
  return `${teamId}__${workDate}`;
}

function loadStore() {
  return readJson(config.storage.timeIntegrityFile, {});
}

function saveStore(store) {
  writeJson(config.storage.timeIntegrityFile, store);
}

function normalizeDate(value) {
  if (!value) return '';
  const v = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  return '';
}

function normalizeClock(value) {
  if (!value) return '';
  const raw = String(value).trim();
  if (!raw) return '';

  const t = raw.replace(/\./g, ':');
  const byColon = t.match(/^(\d{1,2}):(\d{1,2})$/);
  if (byColon) {
    const hh = Number(byColon[1]);
    const mm = Number(byColon[2]);
    if (hh >= 0 && hh <= 23 && mm >= 0 && mm <= 59) {
      return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
    }
    return '';
  }

  const digits = t.replace(/\D/g, '');
  if (!digits) return '';

  let hh;
  let mm;
  if (digits.length <= 2) {
    hh = Number(digits);
    mm = 0;
  } else if (digits.length === 3) {
    hh = Number(digits.slice(0, 1));
    mm = Number(digits.slice(1, 3));
  } else if (digits.length === 4) {
    hh = Number(digits.slice(0, 2));
    mm = Number(digits.slice(2, 4));
  } else {
    return '';
  }

  if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return '';
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

function ensureContext(store, teamId, workDate) {
  const k = key(teamId, workDate);
  if (!store[k]) {
    store[k] = {
      teamId,
      workDate,
      slots: {},
      updated_at: new Date().toISOString()
    };
  }
  return { k, ctx: store[k] };
}

function ensureSlot(ctx, slotNo) {
  if (!ctx.slots[slotNo]) ctx.slots[slotNo] = {};
  return ctx.slots[slotNo];
}

function validateAndPreparePayload({ teamId, workDate, payload }) {
  const store = loadStore();
  const { ctx } = ensureContext(store, teamId, workDate);
  const nextPayload = JSON.parse(JSON.stringify(payload || {}));
  const slots = Array.isArray(nextPayload.slots) ? nextPayload.slots : [];

  for (const slot of slots) {
    const slotNo = String(slot.slot_no || '');
    if (!slotNo) continue;
    const slotState = ctx.slots[slotNo] || {};

    for (const pair of FIELD_PAIRS) {
      const currentTime = normalizeClock(slot[pair.timeKey]);
      let currentDate = normalizeDate(slot[pair.dateKey]);
      if (currentTime && !currentDate) currentDate = workDate;

      const locked = slotState[pair.timeKey];
      if (!locked) {
        slot[pair.timeKey] = currentTime || null;
        slot[pair.dateKey] = currentDate || null;
        continue;
      }

      const lockedDate = locked.date || workDate;
      const lockedTime = locked.time || '';

      if (!currentTime) {
        // Auto-restore immutable time to avoid accidental clearing.
        slot[pair.timeKey] = lockedTime;
        slot[pair.dateKey] = lockedDate;
        continue;
      }

      if (currentTime !== lockedTime || (currentDate || workDate) !== lockedDate) {
        throw new Error(`${pair.label} No.${slotNo} sudah terkunci di ${lockedDate} ${lockedTime}. Gunakan reset resmi jika perlu koreksi.`);
      }

      slot[pair.timeKey] = lockedTime;
      slot[pair.dateKey] = lockedDate;
    }
  }

  return { payload: nextPayload };
}

function commitFromPayload({ teamId, workDate, payload }) {
  const store = loadStore();
  const { k, ctx } = ensureContext(store, teamId, workDate);
  const slots = Array.isArray(payload?.slots) ? payload.slots : [];
  const nowIso = new Date().toISOString();

  for (const slot of slots) {
    const slotNo = String(slot.slot_no || '');
    if (!slotNo) continue;
    const slotState = ensureSlot(ctx, slotNo);

    for (const pair of FIELD_PAIRS) {
      if (slotState[pair.timeKey]) continue;
      const t = normalizeClock(slot[pair.timeKey]);
      if (!t) continue;
      const d = normalizeDate(slot[pair.dateKey]) || workDate;
      slotState[pair.timeKey] = {
        date: d,
        time: t,
        locked_at: nowIso
      };
    }
  }

  ctx.updated_at = nowIso;
  store[k] = ctx;
  saveStore(store);
}

module.exports = {
  validateAndPreparePayload,
  commitFromPayload
};

