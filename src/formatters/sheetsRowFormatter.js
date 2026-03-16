const DEFAULT_TIMEZONE = 'Asia/Jakarta';

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
    return raw;
  }

  const digits = t.replace(/\D/g, '');
  if (!digits) return raw;

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
    return raw;
  }

  if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return raw;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

function normalizeDate(value) {
  if (!value) return '';
  const v = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  return v;
}

function canonicalName(v) {
  if (!v) return '';
  return String(v).trim().replace(/\s+/g, ' ');
}

function assertIdempotencyKey(idempotencyKey) {
  if (!idempotencyKey || String(idempotencyKey).trim() === '') {
    throw new Error('idempotencyKey is required for safe retry and dedupe.');
  }
}

function buildSheetsRows(report, options = {}) {
  const idempotencyKey = options.idempotencyKey;
  assertIdempotencyKey(idempotencyKey);

  const meta = report.report_meta || {};
  const teamStart = meta.team_start || {};
  const slots = Array.isArray(report.slots) ? report.slots : [];

  return slots.map((slot) => {
    const slotNo = String(slot.slot_no || '').padStart(2, '0');
    return {
      dedupe_key: `${idempotencyKey}:slot:${slotNo}`,
      submission_key: idempotencyKey,
      prd_date: normalizeDate(meta.prd_date),
      timezone: meta.timezone || DEFAULT_TIMEZONE,
      submitted_at_system: meta.submitted_at_system || '',
      team_start_label: canonicalName(teamStart.label),
      shift_start: canonicalName(teamStart.shift),
      pelapor_list: (teamStart.members || []).map(canonicalName).filter(Boolean).join(', '),
      team_finish: canonicalName(meta.team_finish),
      handover_time: normalizeClock(meta.handover_time),
      slot_no: slot.slot_no,
      status_enum: canonicalName(slot.status_enum),
      notes: canonicalName(slot.notes),
      tgl_masuk: normalizeDate(slot.tgl_masuk),
      jam_masuk: normalizeClock(slot.jam_masuk),
      tgl_defros: normalizeDate(slot.tgl_defros),
      jam_defros: normalizeClock(slot.jam_defros),
      jam_estimasi_defrost: normalizeClock(slot.jam_estimasi_defrost),
      jam_estimasi_keluar: normalizeClock(slot.jam_estimasi_keluar),
      tgl_selesai_dry: normalizeDate(slot.tgl_selesai_dry),
      jam_selesai_dry: normalizeClock(slot.jam_selesai_dry),
      partial_out: slot.partial_out ? 'yes' : 'no',
      jam_keluar_sebagian: normalizeClock(slot.jam_keluar_sebagian),
      jam_estimasi_sisa: normalizeClock(slot.jam_estimasi_sisa),
      petugas_masuk: canonicalName(slot.petugas_masuk),
      petugas_keluar: canonicalName(slot.petugas_keluar),
      tgl_turun_packing: normalizeDate(slot.tgl_turun_packing),
      jam_turun_packing: normalizeClock(slot.jam_turun_packing),
      status_isi: canonicalName(slot.status_isi),
      atas_izin: canonicalName(slot.atas_izin)
    };
  });
}

module.exports = {
  buildSheetsRows
};
