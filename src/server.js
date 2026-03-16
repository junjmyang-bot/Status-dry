const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const service = require('./services/submitReport');
const config = require('./config');
const pendingQueue = require('./persistence/pendingQueue');
const { readJson } = require('./lib/fileStore');

const HOST = process.env.HOST || '0.0.0.0';
const PORT = Number(process.env.PORT || 8787);

const ROOT = path.resolve(__dirname, '..');
const PUBLIC_DIR = path.join(ROOT, 'public');

function getSecurityState() {
  const telegramReady = Boolean(config.telegram.botToken && config.telegram.chatId);
  const sheetsReady = Boolean(config.sheets.webhookUrl);
  const appLocked = !(telegramReady && sheetsReady);
  return {
    app_locked: appLocked,
    reason: appLocked ? 'App locked: integration secrets are not configured.' : '',
    telegram_ready: telegramReady,
    sheets_ready: sheetsReady
  };
}

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(payload, null, 2));
}

function sendFile(res, filePath, contentType) {
  try {
    const raw = fs.readFileSync(filePath);
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(raw);
  } catch (_) {
    sendJson(res, 404, { ok: false, error: 'Not found' });
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
    });
    req.on('end', () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (err) {
        reject(new Error('Invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

function loadState() {
  const security = getSecurityState();
  return {
    pending_queue: pendingQueue.loadQueue(),
    team_locks: readJson(config.storage.teamLockFile, {}),
    root_messages: readJson(config.storage.rootMessageFile, {}),
    integrations: {
      telegram_ready: security.telegram_ready,
      sheets_ready: security.sheets_ready
    },
    security: {
      app_locked: security.app_locked,
      reason: security.reason
    }
  };
}

async function handleApi(req, res, pathname) {
  try {
    if (req.method === 'GET' && pathname === '/api/sample') {
      const samplePath = path.join(ROOT, 'report.sample.json');
      const sample = readJson(samplePath, {});
      return sendJson(res, 200, { ok: true, sample });
    }

    if (req.method === 'GET' && pathname === '/api/state') {
      return sendJson(res, 200, { ok: true, state: loadState() });
    }

    const security = getSecurityState();
    if (req.method === 'POST' && security.app_locked) {
      return sendJson(res, 423, {
        ok: false,
        error: security.reason
      });
    }

    if (req.method === 'POST' && pathname === '/api/open') {
      const body = await readBody(req);
      const lock = service.openTeam(body.teamId, body.workDate, body.lockOwner);
      return sendJson(res, 200, { ok: true, lock });
    }

    if (req.method === 'POST' && pathname === '/api/takeover') {
      const body = await readBody(req);
      const lock = service.takeOverTeam(body.teamId, body.workDate, body.lockOwner);
      return sendJson(res, 200, { ok: true, lock });
    }

    if (req.method === 'POST' && pathname === '/api/submit') {
      const body = await readBody(req);
      const result = await service.submitReport({
        payload: body.payload,
        teamId: body.teamId,
        workDate: body.workDate,
        lockOwner: body.lockOwner,
        lockToken: body.lockToken,
        expectedVersion: Number(body.expectedVersion)
      });
      return sendJson(res, 200, { ok: true, result });
    }

    if (req.method === 'POST' && pathname === '/api/retry') {
      const result = await service.retryPending();
      return sendJson(res, 200, { ok: true, result });
    }

    return sendJson(res, 404, { ok: false, error: 'Unknown API route' });
  } catch (err) {
    return sendJson(res, 400, { ok: false, error: err.message });
  }
}

const server = http.createServer(async (req, res) => {
  const parsed = url.parse(req.url, true);
  const pathname = parsed.pathname || '/';

  if (pathname.startsWith('/api/')) {
    return handleApi(req, res, pathname);
  }

  if (req.method === 'GET' && pathname === '/') {
    return sendFile(res, path.join(PUBLIC_DIR, 'index.html'), 'text/html; charset=utf-8');
  }

  return sendJson(res, 404, { ok: false, error: 'Not found' });
});

server.listen(PORT, HOST, () => {
  console.log(`Dry report app running: http://${HOST}:${PORT}`);
});
