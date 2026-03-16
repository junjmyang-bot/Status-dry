const { buildTelegramMessages } = require('./formatters/telegramFormatter');
const { buildSheetsRows } = require('./formatters/sheetsRowFormatter');

const report = {
  report_meta: {
    prd_date: '2026-03-05',
    timezone: 'Asia/Jakarta',
    submitted_at_system: '2026-03-05T14:40:00+07:00',
    team_start: { label: 'Aris&Fauzan', shift: 'Shift 1', members: ['Aris', 'Fauzan'] },
    team_finish: ''
  },
  slots: [
    { slot_no: 2, status_enum: 'SIAP_TURUN', jam_masuk: '14:00', jam_estimasi_keluar: '14:30', jam_selesai_dry: '14:30', petugas_masuk: 'Fauzan', status_isi: 'dry ulang pp bar & is', atas_izin: 'aris' },
    { slot_no: 6, status_enum: 'SELESAI_DRY', jam_masuk: '01.17', jam_defros: '00.47', jam_estimasi_keluar: '11.17', jam_selesai_dry: '10:20', petugas_masuk: 'Alnedy', status_isi: 'pp bar', atas_izin: 'ade' },
    { slot_no: 11, status_enum: 'KOSONG', notes: 'khusus dry ulang' }
  ]
};

const telegram = buildTelegramMessages(report, { safeLimit: 500 });
const rows = buildSheetsRows(report, { idempotencyKey: 'dry-2026-03-05-shift1-v1' });

console.log('TELEGRAM_PARTS=' + telegram.length);
console.log(telegram[0].text.split('\n').slice(0, 12).join('\n'));
console.log('ROWS=' + rows.length);
console.log(JSON.stringify(rows[0], null, 2));
