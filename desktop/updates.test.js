'use strict';
// Tests for updates.js without a real release: a fake autoUpdater and dialog stand in for Electron's.
//   node updates.test.js
const assert = require('assert');
const EventEmitter = require('events');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { setupUpdates, sizeText } = require('./updates');

const tick = () => new Promise((r) => setTimeout(r, 20));

function rig(answers, prefsFile) {
  const u = new EventEmitter();
  u.downloads = 0;
  u.checks = 0;
  u.downloadUpdate = () => { u.downloads++; return Promise.resolve(); };
  u.checkForUpdates = () => { u.checks++; };
  const shown = [];
  const dialog = { showMessageBox: async (_w, opts) => { shown.push(opts); return { response: answers.shift() }; } };
  const bar = [];
  const win = { setProgressBar: (v) => bar.push(v) };
  let restarted = 0;
  setupUpdates({ autoUpdater: u, dialog, getWindow: () => win, prefsFile, onRestart: () => { restarted++; }, delayMs: 5 });
  return { u, shown, bar, restarted: () => restarted };
}

(async () => {
  const prefs = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'mrsolis-upd-')), 'update-prefs.json');
  const info = { version: '3.1.0', files: [{ size: 723517440 }] };

  // 1. it asks first, with the size; downloads only on "Download"; shows progress; restarts on "Restart now"
  let t = rig([0, 0], prefs);
  assert.strictEqual(t.u.autoDownload, false, 'must never download on its own');
  await tick();
  assert.strictEqual(t.u.checks, 1, 'checks for updates after start');
  t.u.emit('update-available', info);
  await tick();
  assert.strictEqual(t.shown.length, 1);
  assert.match(t.shown[0].message, /MrSOLIS 3\.1\.0 is available/);
  assert.match(t.shown[0].detail, /up to 690 MB/);
  assert.deepStrictEqual(t.shown[0].buttons, ['Download', 'Not now', 'Skip this version']);
  assert.strictEqual(t.u.downloads, 1, 'downloads after "Download"');
  t.u.emit('download-progress', { percent: 42 });
  assert.strictEqual(t.bar.at(-1), 0.42);
  t.u.emit('update-downloaded', info);
  await tick();
  assert.strictEqual(t.bar.at(-1), -1, 'clears the taskbar progress');
  assert.match(t.shown[1].message, /ready to install/);
  assert.strictEqual(t.restarted(), 1, '"Restart now" restarts');

  // 2. "Not now": nothing downloads, nothing saved
  t = rig([1], prefs);
  t.u.emit('update-available', info);
  await tick();
  assert.strictEqual(t.u.downloads, 0);
  assert.ok(!fs.existsSync(prefs));

  // 3. "Skip this version": remembered; the same version isn't offered again, a newer one is
  t = rig([2], prefs);
  t.u.emit('update-available', info);
  await tick();
  assert.strictEqual(JSON.parse(fs.readFileSync(prefs, 'utf8')).skip, '3.1.0');
  t = rig([1], prefs);
  t.u.emit('update-available', info);
  await tick();
  assert.strictEqual(t.shown.length, 0, 'skipped version not offered again');
  t.u.emit('update-available', { version: '3.2.0', files: [{ size: 50 * 1024 * 1024 }] });
  await tick();
  assert.strictEqual(t.shown.length, 1, 'a newer version is offered');
  assert.match(t.shown[0].detail, /up to 50 MB/);

  // 4. offline / errors: silent, and the taskbar progress is cleared
  t = rig([], prefs);
  t.u.emit('error', new Error('offline'));
  assert.strictEqual(t.bar.at(-1), -1);

  assert.strictEqual(sizeText(0), 'a download');
  assert.strictEqual(sizeText(1.6 * 1024 ** 3), 'up to 1.6 GB');
  console.log('updates.js: all checks passed');
})().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
