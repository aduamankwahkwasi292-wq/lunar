'use strict';
/*
 * Lunar desktop shell (Electron).
 *
 * On launch it spawns the bundled Python backend (the PyInstaller "lunar-backend"
 * binary in production, or `python -m backend.run` in dev), points it at the
 * bundled GGUF models and a writable user-data dir, waits for it to come up
 * behind a splash screen, then loads the app. The backend serves the whole UI,
 * so this shell is just a thin native wrapper. Everything is 100% local.
 *
 * MrSOLIS 3: the UI is a design image (frontend/static/mrsolis3-ui.webp) with its
 * own title bar and window buttons, so the window is frameless, keeps the image's
 * aspect ratio, and preload.js gives the page minimize / maximize / close.
 */

const { app, BrowserWindow, Menu, session, shell, dialog, ipcMain, screen, clipboard } = require('electron');
const { spawn, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const http = require('http');
const net = require('net');
const { fileURLToPath } = require('url');
const { autoUpdater } = require('electron-updater');
const { setupUpdates } = require('./updates');
const licence = require('./licence');

// ---- hardening (2026-10-29) -------------------------------------------------
// The installed app: the licence's test switches are off (licence.lock), nobody may attach a debugger or drive
// its windows remotely (either would let the licence check be stepped over), and DevTools are gone. At packaging
// (build/harden.js) this code is scrambled, app.asar is sealed into the exe (Electron stops if it changes), the
// engine's files are fingerprinted (engineIntact), and the binary refuses NODE_OPTIONS, --inspect and plain Node.
if (app.isPackaged) {
  licence.lock();
  if (['remote-debugging-port', 'remote-debugging-pipe', 'inspect', 'inspect-brk', 'js-flags']
    .some((s) => app.commandLine.hasSwitch(s))) process.exit(1);
}
const DEVTOOLS = !app.isPackaged;

/** Installed app: the engine's files are the ones we shipped (fingerprints made at packaging, in integrity.json
 *  inside the sealed app.asar). An engine with its licence check cut out is refused before it ever starts. */
function engineIntact() {
  if (!app.isPackaged) return true;
  try {
    const { files } = JSON.parse(fs.readFileSync(path.join(__dirname, 'integrity.json'), 'utf8'));
    const list = Object.entries(files || {});
    return list.length > 0 && list.every(([rel, want]) =>
      crypto.createHash('sha256').update(fs.readFileSync(path.join(process.resourcesPath, rel))).digest('hex') === want);
  } catch (_) {
    return false;
  }
}
// A secret made for this launch. The backend answers only requests that carry it (backend/guard.py): the cookie
// our windows get, or the header our own checks send — no website and no other program can use it.
const BACKEND_TOKEN = crypto.randomBytes(24).toString('base64url');

let backendProc = null;
let mainWindow = null;
let splash = null;
let backendPort = 0;

// Lunar's own icon for the window + taskbar (shipped as an extraResource in prod).
function appIcon() {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'icon.ico')
    : path.join(__dirname, 'icon.ico');
}

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
    const req = http.get(url, { timeout: timeoutMs, headers: { 'x-mrsolis': BACKEND_TOKEN } }, (res) => {
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

// Up = the backend answers. Whether a brain is ready is shown inside MrSOLIS (the status chip, and the brain chooser
// on a first start). This used to wait for a ready brain, and a new install has none until the student downloads
// one, so MrSOLIS 3.0.0–3.0.1 never opened for a new student: "did not start in time" (2026-11-03).
async function waitForHealth(port, engine, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (engine.failed) throw new Error(engine.failed);
    try {
      await httpGetJSON(`http://127.0.0.1:${port}/api/health`, 10000);   // a slow PC answers late while it warms up
      return true;
    } catch (_) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('The Lunar engine did not start in time.');
}

// What the backend says (its errors too) is kept in <userData>/logs/engine.log: MrSOLIS's windows have no console,
// so on a student's computer it went nowhere. The backend writes there itself when it has no pipe (backend/run.py).
function engineLogFile() {
  return path.join(app.getPath('userData'), 'logs', 'engine.log');
}

function openEngineLog() {
  const file = engineLogFile();
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    if (fs.existsSync(file) && fs.statSync(file).size > 1024 * 1024) fs.renameSync(file, file.replace(/\.log$/, '.old.log'));
    const out = fs.createWriteStream(file, { flags: 'a' });
    out.on('error', () => { /* a full disk must not stop MrSOLIS */ });
    out.write(`\n---- MrSOLIS ${app.getVersion()} · ${new Date().toISOString()} ----\n`);
    return out;
  } catch (_) {
    return null;
  }
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
    LUNAR_PARENT_PID: String(process.pid),       // the backend quits by itself if this app goes away
    LUNAR_TOKEN: BACKEND_TOKEN,                  // ...and answers only us
    // auto = the bundled GGUFs via llama.cpp when present, else Ollama (dev machines)
    LUNAR_LLM_BACKEND: process.env.LUNAR_LLM_BACKEND || 'auto',
  };
  const log = openEngineLog();
  const keep = (d) => { if (log) log.write(d); };
  const engine = { failed: '' };
  const proc = spawn(cmd, args, { cwd, env, windowsHide: true });
  backendProc = proc;
  proc.stdout.on('data', (d) => { process.stdout.write(`[backend] ${d}`); keep(d); });
  proc.stderr.on('data', (d) => { process.stderr.write(`[backend] ${d}`); keep(d); });
  // blocked or missing (security software, a damaged install): say so now, not after the wait
  proc.on('error', (e) => {
    engine.failed = `MrSOLIS couldn't start its engine (${e.message}).`;
    keep(`[MrSOLIS] couldn't start the engine: ${e.message}\n`);
  });
  proc.on('exit', (code) => {
    if (backendProc === proc) backendProc = null;
    keep(`[MrSOLIS] the engine stopped (code ${code})\n`);
    if (!mainWindow) {                                // still starting: the start-up error says it, once
      engine.failed = engine.failed || `The Lunar engine stopped while starting (code ${code}).`;
      return;
    }
    if (code && code !== 0 && !app.isQuitting) {
      dialog.showErrorBox('Lunar', `The Lunar engine stopped unexpectedly (code ${code}).`);
    }
  });
  proc.on('close', () => { if (log) log.end(); });
  await waitForHealth(backendPort, engine);
  // our windows carry this launch's secret to the backend: a cookie sent only by its own pages, unreadable by scripts
  await session.defaultSession.cookies.set({ url: `http://127.0.0.1:${backendPort}`, name: 'mrsolis', value: BACKEND_TOKEN,
    httpOnly: true, sameSite: 'strict' });
  return backendPort;
}

// Every window shows only MrSOLIS's own pages: a link in a slide, or text slipped into one, can't turn a window that
// holds MrSOLIS's window controls into a web page. (The main window opens links in the student's browser.)
function ownPage(url) {
  try {
    const u = new URL(url);
    if (u.protocol === 'file:') return path.resolve(fileURLToPath(u)).startsWith(path.resolve(__dirname) + path.sep);
    return !!backendPort && u.origin === `http://127.0.0.1:${backendPort}`;
  } catch (_) {
    return false;
  }
}
app.on('web-contents-created', (_e, contents) => {
  contents.on('will-navigate', (ev, url) => { if (!ownPage(url)) ev.preventDefault(); });
  contents.on('will-redirect', (ev, url) => { if (!ownPage(url)) ev.preventDefault(); });
  contents.on('will-attach-webview', (ev) => ev.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
});

function killBackend() {
  if (!backendProc) return;
  const proc = backendProc;
  backendProc = null;
  try {
    if (process.platform === 'win32') {
      // wait for it: a fire-and-forget taskkill died with the app and left the backend running
      spawnSync('taskkill', ['/pid', String(proc.pid), '/T', '/F'], { windowsHide: true, timeout: 5000 });
    } else {
      proc.kill('SIGTERM');
      setTimeout(() => { try { proc.kill('SIGKILL'); } catch (_) {} }, 2000);
    }
  } catch (_) { /* already gone */ }
}

function createSplash() {
  splash = new BrowserWindow({
    width: 460, height: 320, frame: false, resizable: false, center: true,
    backgroundColor: '#0a0a0f', show: true, icon: appIcon(), webPreferences: { devTools: DEVTOOLS },
  });
  splash.loadFile(path.join(__dirname, 'splash.html'));
}

// The MrSOLIS 3 design image is 1449×1086 (4:3). The page fills any window
// at least that wide edge to edge (frontend/static/mrsolis-overlay.css), so the
// window opens maximized; its restored size stays at least 4:3.
const UI_ASPECT = 1449 / 1086;

function createMainWindow(port) {
  const work = screen.getPrimaryDisplay().workAreaSize;
  const height = Math.min(900, work.height);
  const width = Math.min(work.width, Math.max(1320, Math.round(height * UI_ASPECT)));
  mainWindow = new BrowserWindow({
    width, height, minWidth: Math.round(600 * UI_ASPECT), minHeight: 600, show: false,
    frame: false, title: 'MrSOLIS 3',
    backgroundColor: '#010206', autoHideMenuBar: true, icon: appIcon(),
    webPreferences: {
      contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: DEVTOOLS,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  mainWindow.loadURL(`http://127.0.0.1:${port}/app`);
  mainWindow.once('ready-to-show', () => {
    if (splash) { splash.destroy(); splash = null; }
    mainWindow.maximize();
    mainWindow.show();
  });
  // Open external links (slide hyperlinks) in the user's real browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http')) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.on('closed', () => {
    mainWindow = null;
    if (sqeWindow && !sqeWindow.isDestroyed()) sqeWindow.close();   // it needs the backend, which goes with MrSOLIS
  });
}

// ---- the SQE window: MrSOLIS 2-AL, maths practice from a student's own question (frontend/sqe.html) ----------
// Opened from Quizzes → SQE and "Practise more like this". One window: asking again brings it forward with the
// new question typed in (the page never drops a practice in progress for it).
let sqeWindow = null;

function openSqe(question) {
  const q = String(question || '').slice(0, 2000);
  if (sqeWindow && !sqeWindow.isDestroyed()) {
    if (sqeWindow.isMinimized()) sqeWindow.restore();
    sqeWindow.focus();
    if (q) sqeWindow.webContents.send('sqe:prefill', q);
    return;
  }
  const work = screen.getPrimaryDisplay().workAreaSize;
  sqeWindow = new BrowserWindow({
    width: Math.min(1100, work.width), height: Math.min(780, work.height), minWidth: 640, minHeight: 520,
    show: false, frame: false, title: 'MrSOLIS 2-AL', backgroundColor: '#000000', autoHideMenuBar: true, icon: appIcon(),
    webPreferences: {
      contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: DEVTOOLS,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  sqeWindow.loadURL(`http://127.0.0.1:${backendPort}/sqe`);
  sqeWindow.webContents.once('did-finish-load', () => { if (q && sqeWindow) sqeWindow.webContents.send('sqe:prefill', q); });
  sqeWindow.once('ready-to-show', () => sqeWindow && sqeWindow.show());
  sqeWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  sqeWindow.on('closed', () => { sqeWindow = null; });
}
ipcMain.on('sqe:open', (e, q) => { if (fromMain(e)) openSqe(q); });

// Window buttons drawn in the design (see preload.js). Only MrSOLIS's own frameless windows may use them.
function fromMain(e) {
  return mainWindow && !mainWindow.isDestroyed() && e.sender === mainWindow.webContents ? mainWindow : null;
}
function fromOwnWindow(e) {
  if (sqeWindow && !sqeWindow.isDestroyed() && e.sender === sqeWindow.webContents) return sqeWindow;
  return fromMain(e);
}
ipcMain.on('win:minimize', (e) => { const w = fromOwnWindow(e); if (w) w.minimize(); });
ipcMain.on('win:toggle-maximize', (e) => {
  const w = fromOwnWindow(e);
  if (w) { if (w.isMaximized()) w.unmaximize(); else w.maximize(); }
});
ipcMain.on('win:close', (e) => { const w = fromOwnWindow(e); if (w) w.close(); });

// ---- updates --------------------------------------------------------------
// Checks GitHub Releases on launch and ASKS before downloading a newer MrSOLIS, showing its size (updates.js).
// Silent when offline or when no newer release exists, so it never blocks startup.
function setupAutoUpdate() {
  if (!app.isPackaged || process.windowsStore) return;   // a Microsoft Store copy is updated by the Store
  setupUpdates({
    autoUpdater,
    dialog,
    getWindow: () => mainWindow,
    prefsFile: path.join(app.getPath('userData'), 'update-prefs.json'),
    onRestart: () => {
      app.isQuitting = true;
      killBackend();
      autoUpdater.quitAndInstall();
    },
  });
}

// ---- licence --------------------------------------------------------------
// The installed app needs a licence (licence.js); dev runs don't, unless LUNAR_LICENCE=1 (testing this screen).
// No licence on this computer -> the activation window (activate.html) comes before anything else. Once
// licensed, MrSOLIS checks once a day, when online, that the licence is still active: a refund cancels it, and
// then MrSOLIS stops and asks for a code again.
const licenceRequired = app.isPackaged || process.env.LUNAR_LICENCE === '1';
const LICENCE_CHECK_EVERY_MS = 3600 * 1000;           // try hourly; licence.dailyCheck asks the server once a day
let licenceFile = '';
let activateWin = null;
let gateDone = null;

function needLicence() {
  return new Promise((resolve) => {
    gateDone = resolve;
    activateWin = new BrowserWindow({
      width: 520, height: 660, frame: false, resizable: false, center: true, title: 'Activate MrSOLIS',
      backgroundColor: '#000000', icon: appIcon(),
      webPreferences: {
        contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: DEVTOOLS,
        preload: path.join(__dirname, 'preload.js'),
      },
    });
    activateWin.loadFile(path.join(__dirname, 'activate.html'));
    activateWin.webContents.once('did-finish-load', () => {
      const p = licence.pendingPurchase(licenceFile);   // paid (or paying) last time MrSOLIS was open: finish it
      if (p) watchPurchase(p);
    });
    activateWin.on('closed', () => { activateWin = null; stopWatching(); resolve(false); });   // closed without activating
  });
}

function fromActivate(e) {
  return activateWin && !activateWin.isDestroyed() && e.sender === activateWin.webContents;
}
ipcMain.handle('licence:info', (e) => {
  if (!fromActivate(e)) return {};
  const p = licence.pendingPurchase(licenceFile);
  const { claim, url, ...purchase } = p || {};             // never hand the claim to the page
  return { email: licence.EMAIL, reason: licence.removedReason(licenceFile), buying: !!p, purchase: p ? purchase : null };
});
ipcMain.handle('licence:activate', async (e, code) => {
  if (!fromActivate(e)) return { ok: false, error: 'not_allowed', message: '' };
  const r = await licence.activate(licenceFile, String(code || '').slice(0, 40), app.getVersion());
  if (r.ok) setTimeout(() => gateDone && gateDone(true), 900);       // long enough to read "Activated"
  return r;
});
ipcMain.handle('licence:quit', (e) => { if (fromActivate(e)) activateWin.close(); });

// ---- buying inside MrSOLIS ------------------------------------------------
// Online (Flutterwave or Paystack): "Buy" opens the provider's page in the browser and MrSOLIS asks the licence
// server every 3 s. Mobile Money straight to the owner (the user, 2026-10-28): the activation screen shows the
// number and a reference, and MrSOLIS asks every 15 s until the owner confirms the payment in the licences window.
// Either way, once it's paid MrSOLIS collects the new code and activates by itself (licence.js,
// licence-server/src/pay.js).
let buying = null;                                     // { claim, url, timer, until, busy }

function buyProgress(data) {
  if (activateWin && !activateWin.isDestroyed()) activateWin.webContents.send('licence:buy-progress', data);
}

function openPaymentPage(url) {
  if (!licence.isPaymentPage(url)) return;
  if (process.env.LUNAR_OPEN_URL_LOG) { fs.appendFileSync(process.env.LUNAR_OPEN_URL_LOG, `${url}\n`); return; }  // tests
  shell.openExternal(url);
}

function stopWatching() {
  if (buying) clearInterval(buying.timer);
  buying = null;
}

function watchPurchase(p) {
  stopWatching();
  const momo = p.method === 'momo';                    // confirmed by hand: check less often, wait longer
  const watch = { claim: p.claim, url: p.url, until: Date.now() + (momo ? 3 * 24 * 3600 : 45 * 60) * 1000, busy: false };
  buying = watch;
  const tick = async () => {
    if (buying !== watch || watch.busy) return;
    if (Date.now() > watch.until) { stopWatching(); buyProgress({ status: 'timeout' }); return; }
    watch.busy = true;
    try {
      const s = await licence.buyStatus(watch.claim);
      if (buying !== watch) return;
      if (s.ok && s.status === 'paid' && s.code) {
        buyProgress({ status: 'paid', code: s.code });
        const r = await licence.activate(licenceFile, s.code, app.getVersion());
        if (r.ok) {
          stopWatching();
          buyProgress({ status: 'activated', code: s.code });
          setTimeout(() => gateDone && gateDone(true), 4000);       // time to note the code
        } else {
          buyProgress({ status: 'paid', code: s.code, message: r.message });   // e.g. offline: the next tick tries again
        }
      } else if (s.ok && s.status === 'rejected') {
        stopWatching();
        buyProgress({ status: 'rejected', method: p.method || 'online' });
      } else if (s.ok) {
        buyProgress({ status: 'pending', attempt: s.attempt });
      } else if (s.error === 'unknown_claim') {
        licence.forgetPurchase(licenceFile);
        stopWatching();
        buyProgress({ status: 'lost' });
      } else {
        buyProgress({ status: 'pending', offline: true });
      }
    } finally {
      watch.busy = false;
    }
  };
  watch.timer = setInterval(tick, momo ? 15000 : 3000);
  tick();
}

ipcMain.handle('licence:price', (e) => (fromActivate(e) ? licence.price() : null));
ipcMain.handle('licence:buy', async (e, email, opts = {}) => {
  if (!fromActivate(e)) return { ok: false, error: 'not_allowed', message: '' };
  const how = opts && opts.method === 'momo' ? { method: 'momo', payer: String(opts.payer || '').slice(0, 20) } : {};
  const r = await licence.buyStart(licenceFile, String(email || '').slice(0, 120), app.getVersion(), undefined, how);
  if (!r.ok) return r;
  watchPurchase(r);
  if (r.method === 'momo') {
    const { claim, ...shown } = r;                     // what to send, where: the page shows it
    return shown;
  }
  openPaymentPage(r.url);
  return { ok: true };
});
ipcMain.handle('licence:copy', (e, text) => { if (fromActivate(e)) clipboard.writeText(String(text || '').slice(0, 100)); });
ipcMain.handle('licence:buy-reopen', (e) => { if (fromActivate(e) && buying) openPaymentPage(buying.url); });
ipcMain.handle('licence:buy-cancel', (e) => { if (fromActivate(e)) stopWatching(); });

async function licenceCheck() {
  const result = await licence.dailyCheck(licenceFile);
  if (result !== 'revoked') return;
  await dialog.showMessageBox(mainWindow && !mainWindow.isDestroyed() ? mainWindow : undefined, {
    type: 'info', title: 'MrSOLIS', buttons: ['OK'],
    message: 'MrSOLIS stopped on this computer.',
    detail: licence.removedReason(licenceFile),
  });
  app.isQuitting = true;
  killBackend();
  app.relaunch();                                      // opens on the activation screen, which says why
  app.exit(0);
}

function startLicenceChecks() {
  if (!licenceRequired) return;
  const run = () => licenceCheck().catch(() => { /* try again next hour */ });
  setTimeout(run, 30 * 1000);                          // not while the brain is loading
  setInterval(run, LICENCE_CHECK_EVERY_MS).unref();
}

// ---- lifecycle ------------------------------------------------------------
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (activateWin) { activateWin.focus(); return; }
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); }
  });

  app.whenReady().then(async () => {
    app.setAppUserModelId('com.lunar.classroom');   // Windows: own taskbar identity + icon
    // installed: only the Edit menu's keys (copy, paste, undo...) — no reload, no DevTools
    if (app.isPackaged) Menu.setApplicationMenu(Menu.buildFromTemplate([{ role: 'editMenu' }]));
    if (!engineIntact()) {
      console.error('MrSOLIS: its files have been changed or damaged');
      dialog.showErrorBox('MrSOLIS', 'MrSOLIS’s files have been changed or damaged, so it can’t start. '
        + 'Install MrSOLIS again to keep using it. Your notes and decks are kept.');
      app.quit();
      return;
    }
    if (licenceRequired) {
      licenceFile = path.join(app.getPath('userData'), 'licence.json');
      if (!licence.status(licenceFile).valid && !(await needLicence())) { app.quit(); return; }
    }
    createSplash();
    if (activateWin) activateWin.destroy();          // after the splash is up, so the app doesn't count as closed
    try {
      const port = await startBackend();
      createMainWindow(port);
      setupAutoUpdate();
      startLicenceChecks();
    } catch (err) {
      if (splash) { splash.destroy(); splash = null; }
      dialog.showErrorBox('Lunar could not start',
        `${String(err && err.message || err)}\n\nWhat the engine said is saved in:\n${engineLogFile()}`);
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
