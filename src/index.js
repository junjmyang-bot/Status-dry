const fs = require('fs');
const path = require('path');

const service = require('./services/submitReport');

async function main() {
  const cmd = process.argv[2] || 'submit';

  if (cmd === 'open') {
    const teamId = String(process.argv[3] || 'dry-team-1');
    const workDate = String(process.argv[4] || '2026-03-05');
    const lockOwner = String(process.argv[5] || 'operator-a');
    const lock = service.openTeam(teamId, workDate, lockOwner);
    console.log(JSON.stringify({ command: 'open', lock }, null, 2));
    return;
  }

  if (cmd === 'takeover') {
    const teamId = String(process.argv[3] || 'dry-team-1');
    const workDate = String(process.argv[4] || '2026-03-05');
    const lockOwner = String(process.argv[5] || 'operator-b');
    const lock = service.takeOverTeam(teamId, workDate, lockOwner);
    console.log(JSON.stringify({ command: 'takeover', lock }, null, 2));
    return;
  }

  if (cmd === 'retry') {
    const result = await service.retryPending();
    console.log(JSON.stringify({ command: 'retry', result }, null, 2));
    return;
  }

  const inputPath = process.argv[3] || path.join(__dirname, '..', 'report.sample.json');
  if (!fs.existsSync(inputPath)) {
    throw new Error(`Missing input file: ${inputPath}`);
  }

  const payload = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const teamId = String(process.argv[4] || 'dry-team-1');
  const workDate = String(process.argv[5] || payload?.report_meta?.prd_date || '2026-03-05');
  const lockOwner = String(process.argv[6] || 'operator-a');
  const lockToken = String(process.argv[7] || '');
  const expectedVersion = Number(process.argv[8] || 1);

  const result = await service.submitReport({
    payload,
    teamId,
    workDate,
    lockOwner,
    lockToken,
    expectedVersion
  });

  console.log(JSON.stringify({ command: 'submit', result }, null, 2));
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
