'use strict';
/*
 * App updates: MrSOLIS asks before it downloads (the user, 2026-10-26). A student's mobile data costs money, and
 * a new version may be a paid one.
 *
 * In the installed app only, it checks GitHub Releases quietly a few seconds after start. If there is a newer
 * version, it says which one and how big the download is, and downloads only after "Download". "Skip this
 * version" stops it asking about that version. The download shows on the taskbar button. When it is done,
 * "Restart now" installs it at once; otherwise it installs the next time MrSOLIS closes (the student chose to
 * get it).
 *
 * Kept apart from main.js so it can be tested without a real release (desktop/updates.test.js).
 */
const fs = require('fs');

function readPrefs(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')) || {}; } catch (_) { return {}; }
}

function writePrefs(file, prefs) {
  try { fs.writeFileSync(file, JSON.stringify(prefs)); } catch (_) { /* can't save: it just asks again */ }
}

/** "about 690 MB" — the installer's size; electron-updater may fetch only the changed parts, so it's "up to". */
function sizeText(bytes) {
  if (!bytes) return 'a download';
  const mb = bytes / (1024 * 1024);
  return mb >= 1000 ? `up to ${(mb / 1024).toFixed(1)} GB` : `up to ${Math.max(1, Math.round(mb))} MB`;
}

/**
 * Wire electron-updater to ask first.
 * @param {object} o  autoUpdater, dialog (Electron's), getWindow() -> the main window or null,
 *                    prefsFile (where "skip this version" is kept), onRestart() (stop the backend, quitAndInstall),
 *                    delayMs (how long after start to check; default 4000)
 */
function setupUpdates({ autoUpdater, dialog, getWindow, prefsFile, onRestart, delayMs = 4000 }) {
  autoUpdater.autoDownload = false;          // never on its own: only after the student says yes
  autoUpdater.autoInstallOnAppQuit = true;   // a downloaded update (which they chose) installs on quit
  let asked = false;

  autoUpdater.on('update-available', async (info) => {
    const prefs = readPrefs(prefsFile);
    if (asked || !info || prefs.skip === info.version) return;
    asked = true;
    const bytes = (info.files || []).reduce((n, f) => n + (f.size || 0), 0);
    const { response } = await dialog.showMessageBox(getWindow(), {
      type: 'info',
      buttons: ['Download', 'Not now', 'Skip this version'],
      defaultId: 0,
      cancelId: 1,
      title: 'Update available',
      message: `MrSOLIS ${info.version} is available.`,
      detail: `Downloading it uses ${sizeText(bytes)} of internet data. You can keep studying while it downloads.\n\n`
        + 'Not now: ask again next time MrSOLIS starts. Skip this version: don\'t ask about it again.',
    });
    if (response === 0) {
      autoUpdater.downloadUpdate().catch(() => {
        const w = getWindow();
        if (w) w.setProgressBar(-1);
      });
    } else if (response === 2) {
      writePrefs(prefsFile, { ...prefs, skip: info.version });
    }
  });

  autoUpdater.on('download-progress', (p) => {
    const w = getWindow();
    if (w && p && typeof p.percent === 'number') w.setProgressBar(Math.max(0, Math.min(1, p.percent / 100)));
  });

  autoUpdater.on('update-downloaded', async (info) => {
    const w = getWindow();
    if (w) w.setProgressBar(-1);
    const { response } = await dialog.showMessageBox(w, {
      type: 'info',
      buttons: ['Restart now', 'Later'],
      defaultId: 0,
      cancelId: 1,
      title: 'Update ready',
      message: `MrSOLIS ${info.version} is ready to install.`,
      detail: 'Restart MrSOLIS to start using it, or it will install the next time you close MrSOLIS. Your work is saved.',
    });
    if (response === 0) onRestart();
  });

  // Offline, or no release yet: say nothing, never block studying.
  autoUpdater.on('error', () => {
    const w = getWindow();
    if (w) w.setProgressBar(-1);
  });
  setTimeout(() => { try { autoUpdater.checkForUpdates(); } catch (_) { /* offline */ } }, delayMs);
}

module.exports = { setupUpdates, sizeText };
