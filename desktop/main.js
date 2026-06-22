'use strict';
/*
 * Lunar desktop shell (Electron).
 *
 * On launch it spawns the bundled Python backend (the PyInstaller "lunar-backend"
 * binary in production, or `python -m backend.run` in dev), points it at the
 * bundled GGUF models and a writable user-data dir, waits for it to come up
 * behind a splash screen, then loads the app. The backend serves the whole UI,
 * so this shell is just a thin native wrapper. Everything is 100% local.
 */

const { app, BrowserWindow, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const net = require('net');
const { autoUpdater } = require('electron-updater');

let backendProc = null;
let mainWindow = null;
let splash = null;
let backendPort = 0;

// ---- helpers --------------------------------------------------------------
function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function resourceRoot() {
  // Where extraResources land in production; the repo root in dev.
  return app.isPackaged ? process.resourcesPath : path.join(__dirname, '..');
}

function modelDir() {
  return path.join(resourceRoot(), 'models');
}

function backendCommand() {
  if (app.isPackaged) {
    const dir = path.join(process.resourcesPath, 'backend');
    const exe = process.platform === 'win32' ? 'lunar-backend.exe' : 'lunar-backend';
    return { cmd: path.join(dir, exe), args: [], cwd: dir };
  }
  // Dev: run the Python backend directly from the repo.
  const py = process.env.LUNAR_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  return { cmd: py, args: ['-m', 'backend.run'], cwd: path.join(__dirname, '..') };
}

function httpGetJSON(url, timeoutMs = 2500) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (e) { reject(e); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

async function waitForHealth(port, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const h = await httpGetJSON(`http://127.0.0.1:${port}/api/health`);
      if (h && h.ok) return true;
      // Backend is up but the model isn't ready (missing GGUF) — surface it.
      if (h && h.error) throw new Error(h.error);
    } catch (_) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('The Lunar engine did not start in time.');
}

async function startBackend() {
  backendPort = await getFreePort();
  const { cmd, args, cwd } = backendCommand();
  const env = {
    ...process.env,
    LUNAR_HOST: '127.0.0.1',
    LUNAR_PORT: String(backendPort),
    LUNAR_MODEL_DIR: modelDir(),
    LUNAR_DATA_DIR: app.getPath('userData'),
    LUNAR_LLM_BACKEND: process.env.LUNAR_LLM_BACKEND || 'llama',
  };
  backendProc = spawn(cmd, args, { cwd, env, windowsHide: true });
  backendProc.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`));
  backendProc.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`));
  backendProc.on('exit', (code) => {
    backendProc = null;
    if (code && code !== 0 && !app.isQuitting) {
      dialog.showErrorBox('Lunar', `The Lunar engine stopped unexpectedly (code ${code}).`);
    }
  });
  await waitForHealth(backendPort);
  return backendPort;
}

function killBackend() {
  if (!backendProc) return;
  const proc = backendProc;
  backendProc = null;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(proc.pid), '/T', '/F']);
    } else {
      proc.kill('SIGTERM');
      setTimeout(() => { try { proc.kill('SIGKILL'); } catch (_) {} }, 2000);
    }
  } catch (_) { /* already gone */ }
}

function createSplash() {
  splash = new BrowserWindow({
    width: 460, height: 320, frame: false, resizable: false, center: true,
    backgroundColor: '#0a0a0f', show: true,
  });
  splash.loadFile(path.join(__dirname, 'splash.html'));
}

function createMainWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1320, height: 860, minWidth: 980, minHeight: 640, show: false,
    backgroundColor: '#0a0a0f', autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  mainWindow.once('ready-to-show', () => {
    if (splash) { splash.destroy(); splash = null; }
    mainWindow.show();
  });
  // Open external links (slide hyperlinks) in the user's real browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http')) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.on('closed', () => { mainWindow = null; });
}

// ---- auto-update ----------------------------------------------------------
// Checks GitHub Releases on launch; if a newer Lunar is published, downloads it
// quietly and offers a one-click "Restart to update". Silent when offline or when
// no newer release exists, so it never blocks startup.
function setupAutoUpdate() {
  if (!app.isPackaged) return;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.on('update-downloaded', (info) => {
    const choice = dialog.showMessageBoxSync(mainWindow, {
      type: 'info',
      buttons: ['Restart now', 'Later'],
      defaultId: 0,
      cancelId: 1,
      title: 'Update available',
      message: `Lunar ${info.version} is ready to install.`,
      detail: 'Restart Lunar to get the latest version. Your work is saved.',
    });
    if (choice === 0) {
      app.isQuitting = true;
      killBackend();
      autoUpdater.quitAndInstall();
    }
  });
  // Never let an update hiccup (offline, no release yet) surface to the user.
  autoUpdater.on('error', () => {});
  setTimeout(() => { try { autoUpdater.checkForUpdates(); } catch (_) {} }, 4000);
}

// ---- lifecycle ------------------------------------------------------------
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); }
  });

  app.whenReady().then(async () => {
    createSplash();
    try {
      const port = await startBackend();
      createMainWindow(port);
      setupAutoUpdate();
    } catch (err) {
      if (splash) { splash.destroy(); splash = null; }
      dialog.showErrorBox('Lunar could not start', String(err && err.message || err));
      app.quit();
    }
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && backendPort) createMainWindow(backendPort);
  });
}

app.on('before-quit', () => { app.isQuitting = true; killBackend(); });
app.on('window-all-closed', () => { killBackend(); app.quit(); });
process.on('exit', killBackend);
