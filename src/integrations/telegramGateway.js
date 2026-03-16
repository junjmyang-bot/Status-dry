const config = require('../config');

function baseUrl() {
  if (!config.telegram.botToken) throw new Error('Missing TELEGRAM_BOT_TOKEN');
  return `https://api.telegram.org/bot${config.telegram.botToken}`;
}

async function callTelegram(method, payload) {
  const resp = await fetch(`${baseUrl()}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  const data = await resp.json();
  if (!resp.ok || !data.ok) {
    const desc = data.description || `HTTP ${resp.status}`;
    throw new Error(`Telegram ${method} failed: ${desc}`);
  }
  return data.result;
}

function normalizeMessageInput(input, options = {}) {
  if (typeof input === 'string') {
    return { text: input, ...options };
  }
  if (input && typeof input === 'object') {
    return input;
  }
  return { text: '' };
}

async function sendMessage(input, options = {}) {
  const message = normalizeMessageInput(input, options);
  const payload = {
    chat_id: config.telegram.chatId,
    text: message.text,
    disable_web_page_preview: true
  };
  if (message.replyToMessageId) payload.reply_to_message_id = message.replyToMessageId;
  if (message.parseMode) payload.parse_mode = message.parseMode;
  return callTelegram('sendMessage', payload);
}

async function editMessage(messageId, input) {
  const message = normalizeMessageInput(input);
  const payload = {
    chat_id: config.telegram.chatId,
    message_id: messageId,
    text: message.text,
    disable_web_page_preview: true
  };
  if (message.parseMode) payload.parse_mode = message.parseMode;
  return callTelegram('editMessageText', payload);
}

module.exports = {
  sendMessage,
  editMessage
};
