'use strict';
/*
 * MrSOLIS's licence, on the student's computer (Behemoth Group's licence server: Downloads\lunar\licence-server).
 *
 *  - Activation: the first time, the student types their code; MrSOLIS sends it with this computer's ID (a
 *    one-way hash of Windows' machine ID, never the ID itself) to the licence server, which records
 *    "code -> computer" and returns a licence signed with Behemoth's private key. It is saved as licence.json in
 *    the app's data folder and checked against PUBLIC_KEY at every start — a forged or copied licence fails.
 *    After activation MrSOLIS works fully offline.
 *  - Daily check (the user, 2026-10-26): once a day, when the computer is online, MrSOLIS asks the server whether
 *    the licence is still active on this computer. If the owner refunded it, the licence is removed and MrSOLIS
 *    asks for a code again. Offline, nothing happens. Licences can't be moved to another computer (for now).
 */
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const { execFileSync } = require('child_process');

// Behemoth Group's public key (licence-server/keys/public.key). Only the matching private key can sign licences.
const PUBLIC_KEY = 'MCowBQYDK2VwAyEABR/9J2efNOtycKskf0HGCYTx1j3WbRauXV8Q7IBh8Bo=';
// Behemoth's licence server on Cloudflare Workers (licence-server/README.md), online since 2026-10-27. Installed
// copies of MrSOLIS keep calling this address, so it must stay (a custom domain can be added beside it later).
const LIVE_SERVER = 'https://mrsolis-licence.jonsonwhocancreate.workers.dev';
const DAY_MS = 24 * 3600 * 1000;
const EMAIL = 'jonsonwhocancreate@gmail.com';

// The test switches (LUNAR_LICENCE_URL: another server; LUNAR_DEVICE_ID: pretend to be another computer) work in
// dev runs only. The installed app calls lock() first (hardening, 2026-10-29): before that, a copied licence.json
// plus LUNAR_DEVICE_ID set to the device in it would have run MrSOLIS on any computer.
let locked = false;
function lock() { locked = true; }
const ENV_SERVER = 'LUNAR_LICENCE_URL', ENV_DEVICE = 'LUNAR_DEVICE_ID';   // as strings, so packaging scrambles them
const testServer = () => (!locked && process.env[ENV_SERVER]) || '';
const server = () => testServer() || LIVE_SERVER;

/** This computer's ID, hashed: the same every time on this Windows install, meaningless to anyone else. */
function deviceId() {
  if (!locked && process.env[ENV_DEVICE]) return process.env[ENV_DEVICE];   // tests: pretend to be another computer
  let raw = '';
  try {
    if (process.platform === 'win32') {
      const out = execFileSync('reg', ['query', 'HKLM\\SOFTWARE\\Microsoft\\Cryptography', '/v', 'MachineGuid'],
        { encoding: 'utf8', windowsHide: true });
      raw = (out.match(new RegExp('MachineGuid\\s+REG_SZ\\s+([0-9a-fA-F-]+)')) || [])[1] || '';   // a string, so scrambled
    } else if (process.platform === 'darwin') {
      const out = execFileSync('ioreg', ['-rd1', '-c', 'IOPlatformExpertDevice'], { encoding: 'utf8' });
      raw = (out.match(/"IOPlatformUUID" = "([^"]+)"/) || [])[1] || '';
    } else {
      raw = fs.readFileSync('/etc/machine-id', 'utf8').trim();
    }
  } catch (_) { /* fall through */ }
  if (!raw) raw = `${os.hostname()}|${os.userInfo().username}|${os.cpus()[0] && os.cpus()[0].model}`;
  return crypto.createHash('sha256').update(`mrsolis-device:${raw}`).digest('hex').slice(0, 40);
}

const publicKey = crypto.createPublicKey({ key: Buffer.from(PUBLIC_KEY, 'base64'), format: 'der', type: 'spki' });
const fromB64url = (s) => Buffer.from(s.replace(/-/g, '+').replace(/_/g, '/'), 'base64');

/** The licence's contents if it is genuine (signed by Behemoth) and for this computer, else null. */
function verify(licence, device) {
  try {
    const [body, sig] = String(licence || '').split('.');
    if (!body || !sig || !crypto.verify(null, Buffer.from(body), publicKey, fromB64url(sig))) return null;
    const payload = JSON.parse(fromB64url(body).toString('utf8'));
    return payload.v === 1 && payload.device === device ? payload : null;
  } catch (_) {
    return null;
  }
}

function readState(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')) || {}; } catch (_) { return {}; }
}

function writeState(file, state) {
  fs.writeFileSync(file, JSON.stringify(state));
}

/** { valid, code, kind } — is MrSOLIS licensed on this computer right now? (No internet needed.) */
function status(file, device = deviceId()) {
  const st = readState(file);
  const payload = verify(st.licence, device);
  return payload ? { valid: true, code: payload.code, kind: payload.kind } : { valid: false };
}

async function post(path, body, timeoutMs = 15000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(server().replace(/\/$/, '') + path, {
      method: body === undefined ? 'GET' : 'POST', headers: { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), signal: ctrl.signal,
    });
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

const MESSAGES = {
  bad_code: 'That doesn’t look like a MrSOLIS code. It looks like MRS-XXXX-XXXX-XXXX — check it and try again.',
  unknown_code: 'That code isn’t recognised. Check it and try again.',
  revoked: 'This code was refunded or cancelled, so it can’t be used.',
  in_use: `This code is already active on another computer. Each licence is for one computer. Questions: ${EMAIL}.`,
  offline: 'MrSOLIS couldn’t reach the licence server. Check your internet connection and try again — you only need it once.',
  bad_reply: 'The licence server sent back something MrSOLIS couldn’t check. Try again later.',
  busy: 'The licence server is busy. Wait a minute and try again.',
};

/** Activate a code on this computer. Returns { ok: true } or { ok: false, error, message }. */
async function activate(file, code, appVersion = '', device = deviceId()) {
  let r;
  try {
    r = await post('/v1/activate', { code, device, app: appVersion });
  } catch (_) {
    return { ok: false, error: 'offline', message: MESSAGES.offline };
  }
  if (!r || !r.ok) {
    const error = (r && r.error) || 'bad_reply';
    return { ok: false, error, message: MESSAGES[error] || MESSAGES.bad_reply };
  }
  const payload = verify(r.licence, device);
  if (!payload) return { ok: false, error: 'bad_reply', message: MESSAGES.bad_reply };
  writeState(file, { licence: r.licence, lastCheck: Date.now() });
  return { ok: true, code: payload.code };
}

/**
 * The daily check: at most once a day, and only when the server can be reached.
 * Returns 'active' | 'not_due' | 'offline' | 'revoked' | 'unlicensed'. On 'revoked' the licence is removed from
 * this computer (removedReason() then says why).
 */
async function dailyCheck(file, { device = deviceId(), now = Date.now(), force = false } = {}) {
  const st = readState(file);
  const payload = verify(st.licence, device);
  if (!payload) return 'unlicensed';
  if (!force && st.lastCheck && now - st.lastCheck < DAY_MS) return 'not_due';
  let r;
  try {
    r = await post('/v1/check', { code: payload.code, device }, 10000);
  } catch (_) {
    return 'offline';                                    // try again next time the computer is online
  }
  if (!r || !r.ok) return 'offline';
  if (r.status === 'active') {
    writeState(file, { ...st, lastCheck: now });
    return 'active';
  }
  if (r.status === 'revoked' || r.status === 'unknown') {
    writeState(file, { removed: 'revoked', removedAt: now });   // the licence goes; the note says why (activation screen)
    return 'revoked';
  }
  return 'offline';
}

const REMOVED = {
  revoked: `This licence was refunded or cancelled, so MrSOLIS stopped on this computer. To keep using it, type another licence code. Questions: ${EMAIL}.`,
};

/** Why the licence was taken off this computer (for the activation screen), or '' if it never was. */
function removedReason(file) {
  return REMOVED[readState(file).removed] || '';
}

// ── buying inside MrSOLIS (Flutterwave or Paystack: Mobile Money or card) ─────────────────────────
// The licence server makes the payment and, once the provider confirms it, the code (licence-server/src/pay.js).
// MrSOLIS opens the provider's page in the browser, then collects the code with the order's claim (a secret only
// this computer has) and activates as usual. The claim is kept in licence.json, so a payment finished after
// MrSOLIS was closed still activates it next time.
const BUY_MESSAGES = {
  not_selling: `Buying inside MrSOLIS isn’t open yet. To buy a code, email ${EMAIL}.`,
  bad_email: 'Type your email address. Your receipt goes there: it’s your proof of payment.',
  bad_payer: 'Type the Mobile Money number you’ll pay from (10 digits, like 024 123 4567).',
  too_many: `You’ve already started paying on this computer. Finish that payment, or email ${EMAIL}.`,
  pay_unavailable: 'The payment service didn’t answer. Try again in a minute.',
  offline: 'MrSOLIS couldn’t reach the licence server. Check your internet connection and try again.',
  busy: 'The licence server is busy. Wait a minute and try again.',
};

/** The payment provider's own checkout, or (in tests, with LUNAR_LICENCE_URL set) a page on this computer. */
function isPaymentPage(url) {
  try {
    const u = new URL(url);
    return (u.protocol === 'https:' && (u.hostname === 'checkout.paystack.com' || u.hostname === 'checkout.flutterwave.com'
        || u.hostname.endsWith('.checkout.flutterwave.com')))
      || (!!testServer() && u.hostname === '127.0.0.1');
  } catch (_) {
    return false;
  }
}

/**
 * The price and the ways to pay: { selling, amount (pesewas), currency, usd (the price in dollars), online, provider, momo }, or null
 * when the server can't be reached. online = the provider's card/MoMo page; momo = { number, network, name } to send
 * to straight (confirmed by the owner).
 */
async function price() {
  try {
    const r = await post('/v1/buy/price', undefined, 8000);
    if (!r || !r.ok) return null;
    const methods = r.methods || (r.selling ? ['online'] : []);
    const testMode = !!r.test && !testServer();                      // an installed MrSOLIS never buys in test mode
    const online = methods.includes('online') && !testMode;
    const momo = methods.includes('momo') && r.momo ? r.momo : null;
    return { selling: online || !!momo, amount: r.amount, currency: r.currency, usd: r.usd || 0,
      online, provider: online ? r.provider || '' : '', momo };
  } catch (_) {
    return null;
  }
}

/**
 * Start buying. Online: { ok: true, url } (the provider's page, to open in the browser). Mobile Money to the owner
 * (opts { method: 'momo', payer }): { ok: true, method: 'momo', momo, reference, payer, amount, currency }, what to
 * send where. Or { ok: false, error, message }.
 */
async function buyStart(file, email, appVersion = '', device = deviceId(), opts = {}) {
  const momo = opts.method === 'momo';
  let r;
  try {
    r = await post('/v1/buy/start', { email, device, app: appVersion, ...(momo ? { method: 'momo', payer: opts.payer } : {}) }, 25000);
  } catch (_) {
    return { ok: false, error: 'offline', message: BUY_MESSAGES.offline };
  }
  if (!r || !r.ok) {
    const error = (r && r.error) || 'bad_reply';
    return { ok: false, error, message: BUY_MESSAGES[error] || MESSAGES.bad_reply };
  }
  if (momo) {
    if (!r.claim || r.method !== 'momo' || !r.momo || !r.reference) return { ok: false, error: 'bad_reply', message: MESSAGES.bad_reply };
    const pending = { claim: r.claim, method: 'momo', reference: r.reference, momo: r.momo, payer: r.payer,
      amount: r.amount, currency: r.currency, at: Date.now() };
    writeState(file, { ...readState(file), pending });
    return { ok: true, ...pending };
  }
  if (!r.claim || !isPaymentPage(r.url)) return { ok: false, error: 'bad_reply', message: MESSAGES.bad_reply };
  writeState(file, { ...readState(file), pending: { claim: r.claim, url: r.url, at: Date.now() } });
  return { ok: true, url: r.url, claim: r.claim };
}

/** Where a purchase is: { ok: true, status: 'pending' | 'paid' | 'rejected', code?, attempt } or { ok: false, error }. */
async function buyStatus(claim) {
  try {
    const r = await post('/v1/buy/status', { claim }, 15000);
    return r && r.ok ? r : { ok: false, error: (r && r.error) || 'bad_reply' };
  } catch (_) {
    return { ok: false, error: 'offline' };
  }
}

/** A purchase started on this computer in the last week and not finished: { claim, url, at }, or null. */
function pendingPurchase(file) {
  const p = readState(file).pending;
  return p && p.claim && Date.now() - p.at < 7 * DAY_MS ? p : null;
}

function forgetPurchase(file) {
  const st = readState(file);
  if (st.pending) { delete st.pending; writeState(file, st); }
}

module.exports = {
  lock, deviceId, verify, status, activate, dailyCheck, removedReason, MESSAGES, EMAIL, DAY_MS,
  price, buyStart, buyStatus, pendingPurchase, forgetPurchase, isPaymentPage, BUY_MESSAGES,
};
