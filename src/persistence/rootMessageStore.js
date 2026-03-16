const { readJson, writeJson } = require('../lib/fileStore');
const config = require('../config');

function loadRootMap() {
  return readJson(config.storage.rootMessageFile, {});
}

function saveRootMap(map) {
  writeJson(config.storage.rootMessageFile, map);
}

function getRoot(teamId, workDate) {
  const key = `${teamId}__${workDate}`;
  return loadRootMap()[key] || null;
}

function setRoot(teamId, workDate, value) {
  const key = `${teamId}__${workDate}`;
  const map = loadRootMap();
  map[key] = value;
  saveRootMap(map);
  return map[key];
}

module.exports = {
  getRoot,
  setRoot
};
