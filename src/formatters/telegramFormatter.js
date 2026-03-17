function cleanText(value) {
  if (value === undefined || value === null) return '';
  return String(value).trim();
}

function toTitleName(value) {
  const text = cleanText(value);
  if (!text) return '';
  return text
    .toLowerCase()
    .replace(/\b\w/g, (match) => match.toUpperCase());
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

function formatSubmittedAt(value) {
  const text = cleanText(value);
  if (!text) return '-';
  const matched = text.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  if (matched) return `${matched[1]} ${matched[2]}`;
  return text;
}

function slotGroup(slot) {
  const status = cleanText(slot.status_enum) || 'KOSONG';
  if (status === 'TIDAK_DIPAKAI') return 'tidak_dipakai';
  if (status === 'KOSONG' || status === 'TURUN_PACKING') return 'kosong';
  return 'aktif';
}

function needsAction(slot) {
  const status = cleanText(slot.status_enum) || 'KOSONG';
  if ((status === 'SIAP_TURUN' || status === 'SELESAI_DRY') && !cleanText(slot.jam_turun_packing)) return true;
  if ((status === 'PROSES' || status === 'DRY_ULANG') && cleanText(slot.jam_selesai_dry)) return true;
  return false;
}

function effectiveDefrostRequired(slot) {
  if (slot.needs_defrost === true || slot.needs_defrost === false) return slot.needs_defrost;
  if (cleanText(slot.jam_defros)) return true;
  return !cleanText(slot.status_isi).toLowerCase().includes('dry ulang');
}

function processStage(slot) {
  const status = cleanText(slot.status_enum) || 'KOSONG';
  if (!['PROSES', 'SIAP_TURUN', 'SELESAI_DRY', 'DRY_ULANG'].includes(status)) return '';
  if (effectiveDefrostRequired(slot) && cleanText(slot.jam_defros) && !cleanText(slot.jam_masuk)) return 'DEFROST';
  if (status === 'DRY_ULANG') return 'SEDANG_DRY_TAMBAHAN';
  if ((status === 'SIAP_TURUN' || status === 'SELESAI_DRY') || (cleanText(slot.jam_selesai_dry) && !cleanText(slot.jam_turun_packing))) return 'MENUNGGU_TURUN';
  if (cleanText(slot.jam_masuk)) return 'SEDANG_DRY';
  return 'LAGI_ISI';
}

function clockMinutes(value) {
  const normalized = normalizeClock(value);
  if (!normalized) return null;
  const [hh, mm] = normalized.split(':').map(Number);
  return hh * 60 + mm;
}

function targetClock(slot) {
  if (processStage(slot) === 'DEFROST' && effectiveDefrostRequired(slot)) return cleanText(slot.jam_estimasi_defrost);
  return cleanText(slot.jam_estimasi_keluar);
}

function currentActionType(slot) {
  const status = cleanText(slot.status_enum) || 'KOSONG';
  const nowMinutes = clockMinutes(new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Jakarta' }));
  const target = clockMinutes(targetClock(slot));
  if (processStage(slot) === 'DEFROST' && target !== null && nowMinutes !== null && nowMinutes >= target) return 'MULAI_DRY';
  if (processStage(slot) === 'MENUNGGU_TURUN') return 'PILIH_TINDAKAN';
  if (processStage(slot) === 'SEDANG_DRY_TAMBAHAN' || processStage(slot) === 'SEDANG_DRY') return 'SELESAI_SETTING';
  return '';
}

function statusLabel(slot) {
  if (cleanText(slot.status_enum) === 'TURUN_PACKING' || cleanText(slot.jam_turun_packing)) return 'LAGI KELUARKAN';
  if (processStage(slot) === 'MENUNGGU_TURUN') return 'MENUNGGU TURUN';
  if (processStage(slot) === 'DEFROST') return 'DEFROST';
  if (processStage(slot) === 'SEDANG_DRY_TAMBAHAN') return 'SEDANG DRY TAMBAHAN';
  if (processStage(slot) === 'SEDANG_DRY') return 'SEDANG DRY';
  if (['PROSES', 'SIAP_TURUN', 'SELESAI_DRY', 'DRY_ULANG'].includes(cleanText(slot.status_enum))) return 'LAGI ISI';
  if (cleanText(slot.status_enum) === 'KOSONG') return 'KOSONG';
  if (cleanText(slot.status_enum) === 'TIDAK_DIPAKAI') return 'TIDAK DIPAKAI';
  return cleanText(slot.status_enum) || '-';
}

function summaryCounts(report) {
  const slots = Array.isArray(report.slots) ? report.slots : [];
  return {
    total: slots.length,
    aktif: slots.filter((slot) => slotGroup(slot) === 'aktif').length,
    perluAksi: slots.filter((slot) => needsAction(slot)).length,
    kosong: slots.filter((slot) => slotGroup(slot) === 'kosong').length,
    tidakDipakai: slots.filter((slot) => slotGroup(slot) === 'tidak_dipakai').length
  };
}

function pickUpdatedSlot(report) {
  const slots = Array.isArray(report.slots) ? report.slots : [];
  const selectedSlot = Number(report.selected_slot || report.report_meta?.selected_slot || 0);
  if (selectedSlot) {
    const found = slots.find((slot) => Number(slot.slot_no) === selectedSlot);
    if (found) return found;
  }
  return slots.find((slot) => needsAction(slot))
    || slots.find((slot) => slotGroup(slot) === 'aktif')
    || slots[0]
    || null;
}

function petugasLabel(slot) {
  return toTitleName(slot.petugas_keluar || slot.petugas_masuk) || '-';
}

function izinLabel(slot) {
  return toTitleName(slot.atas_izin) || '-';
}

function productLabel(slot) {
  return cleanText(slot.status_isi).toUpperCase() || '-';
}

function buildTelegramMainMessage(report) {
  const counts = summaryCounts(report);
  const prdDate = cleanText(report.report_meta?.prd_date) || '-';
  const shift = cleanText(report.report_meta?.team_start?.shift) || '-';

  return [
    '[SOI] Laporan Dry',
    `Tgl Produksi: ${prdDate}`,
    `Shift: ${shift}`,
    '',
    `Total Slot: ${counts.total}`,
    `Slot Aktif: ${counts.aktif}`,
    `Perlu Aksi: ${counts.perluAksi}`,
    `Kosong: ${counts.kosong}`,
    `Tidak Dipakai: ${counts.tidakDipakai}`
  ].join('\n');
}

function buildTelegramUpdateReply(report) {
  const slot = pickUpdatedSlot(report);
  const submittedAt = formatSubmittedAt(report.report_meta?.submitted_at_system);

  if (!slot) {
    return [
      '@SOI_DRY_Laporan',
      'Laporan sudah diperbarui.',
      '',
      submittedAt,
      'No.- | -',
      'Status: -',
      'Petugas: -',
      'Izin: -'
    ].join('\n');
  }

  return [
    '@SOI_DRY_Laporan',
    'Laporan sudah diperbarui.',
    '',
    submittedAt,
    `No.${slot.slot_no} | ${productLabel(slot)}`,
    `Status: ${statusLabel(slot)}`,
    `Petugas: ${petugasLabel(slot)}`,
    `Izin: ${izinLabel(slot)}`
  ].join('\n');
}

function buildTelegramMessages(report) {
  return [
    { part: 1, text: buildTelegramMainMessage(report) },
    { part: 2, text: buildTelegramUpdateReply(report) }
  ];
}

module.exports = {
  buildTelegramMainMessage,
  buildTelegramUpdateReply,
  buildTelegramMessages,
  normalizeClock,
  toTitleName
};
