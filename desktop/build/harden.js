'use strict';
/*
 * electron-builder afterPack hook: hardening (2026-10-29/30). After electron-builder has packed the app:
 *
 *  1. Scramble MrSOLIS's own main-process code (main.js, licence.js, preload.js, updates.js) inside app.asar with
 *     javascript-obfuscator, so the licence gate can't simply be read and edited.
 *  2. Fingerprint the engine (resources/backend: lunar-backend.exe and its compiled licence check, gate.*.pyd)
 *     into app.asar's integrity.json. main.js refuses to start a changed engine.
 *  3. Windows, signed builds only (sealWindowsExe): write app.asar's header hash into the exe (resource
 *     INTEGRITY/ELECTRONASAR, the format Electron 30+ reads; the same as Electron Packager's src/resedit.ts) and flip
 *     Electron's fuses (see FUSES below), so a changed app.asar makes Electron stop, and no debugger, NODE_OPTIONS or
 *     plain-Node run can get in. Linux: the fuses (not the integrity check, which Linux can't read).
 *
 * Electron keeps the fuses as bytes after a fixed marker in its binary (what @electron/fuses flips; electron-builder
 * 24 has no setting for them). Layout checked on Electron 31.7.7: version 1, 8 fuses, "10110001".
 * macOS: steps 1 and 2 only — flipping fuses or editing the binary there breaks its signature.
 */
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SENTINEL = Buffer.from('dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX');
// Electron's FuseV1Options: 0 RunAsNode, 1 EnableCookieEncryption, 2 EnableNodeOptionsEnvironmentVariable,
// 3 EnableNodeCliInspectArguments, 4 EnableEmbeddedAsarIntegrityValidation, 5 OnlyLoadAppFromAsar,
// 6 LoadBrowserProcessSpecificV8Snapshot, 7 GrantFileProtocolExtraPrivileges
const FUSES = { 0: '0', 2: '0', 3: '0', 4: '1', 5: '1' };
const OWN_CODE = ['main.js', 'licence.js', 'preload.js', 'updates.js'];
const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

/** Flip the fuses in an Electron binary in place; returns the fuse wire after, e.g. "00001101". */
function flipFuses(exe, want = FUSES) {
  const buf = fs.readFileSync(exe);
  const at = buf.indexOf(SENTINEL);
  if (at < 0 || buf.indexOf(SENTINEL, at + 1) >= 0) throw new Error(`fuses: expected exactly one fuse wire in ${exe}`);
  const version = buf[at + SENTINEL.length];
  const count = buf[at + SENTINEL.length + 1];
  const start = at + SENTINEL.length + 2;
  if (version !== 1 || count < 6) throw new Error(`fuses: unknown fuse wire in ${exe} (version ${version}, ${count} fuses)`);
  for (const [i, v] of Object.entries(want)) {
    const now = String.fromCharCode(buf[start + Number(i)]);
    if (now !== '0' && now !== '1') throw new Error(`fuses: fuse ${i} is "${now}" in ${exe}`);   // "r" = removed
    buf[start + Number(i)] = v.charCodeAt(0);
  }
  fs.writeFileSync(exe, buf);
  return buf.subarray(start, start + count).toString('latin1');
}

/** Scramble MrSOLIS's own code. Moderate settings: nothing that changes how the code behaves or slows start-up.
 *  preload.js runs in the sandboxed page, so it is treated as browser code. */
function obfuscate(code, file = '') {
  const JavaScriptObfuscator = require('javascript-obfuscator');
  return JavaScriptObfuscator.obfuscate(code, {
    target: file === 'preload.js' ? 'browser-no-eval' : 'node', compact: true, simplify: true, identifierNamesGenerator: 'hexadecimal',
    // renameGlobals: a CommonJS file's top level is the module's own scope, so its names can go too
    renameGlobals: true, stringArray: true, stringArrayEncoding: ['base64'], stringArrayThreshold: 1,
    stringArrayRotate: true, stringArrayShuffle: true, splitStrings: true, splitStringsChunkLength: 8,
    controlFlowFlattening: true, controlFlowFlatteningThreshold: 0.4, deadCodeInjection: false,
    selfDefending: false, debugProtection: false, transformObjectKeys: false, unicodeEscapeSequence: false,
  }).getObfuscatedCode();
}

/** The engine's files whose fingerprints main.js checks before it starts the engine (relative to resources/). */
function engineFiles(resources) {
  const dir = path.join(resources, 'backend');
  const out = [];
  for (const name of ['lunar-backend.exe', 'lunar-backend']) if (fs.existsSync(path.join(dir, name))) out.push(`backend/${name}`);
  for (const sub of ['_internal/backend', 'backend']) {          // PyInstaller 6 puts packages under _internal/
    const pkg = path.join(dir, ...sub.split('/'));
    if (!fs.existsSync(pkg)) continue;
    for (const f of fs.readdirSync(pkg)) if (/^gate\..*\.(pyd|so)$/.test(f)) out.push(`backend/${sub}/${f}`);
  }
  return out;
}

/** Rebuild app.asar with the scrambled code and the engine's fingerprints; returns what was done. */
async function hardenAsar(resources) {
  const asar = require('@electron/asar');
  const archive = path.join(resources, 'app.asar');
  if (fs.existsSync(`${archive}.unpacked`)) throw new Error('harden: app.asar has unpacked files; this hook does not handle them yet');
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'mrsolis-harden-'));
  try {
    const dir = path.join(work, 'app');
    asar.extractAll(archive, dir);
    const done = [];
    for (const f of OWN_CODE) {
      const file = path.join(dir, f);
      if (!fs.existsSync(file)) continue;
      fs.writeFileSync(file, obfuscate(fs.readFileSync(file, 'utf8'), f));
      done.push(f);
    }
    const files = {};
    for (const rel of engineFiles(resources)) files[rel] = sha256(fs.readFileSync(path.join(resources, rel)));
    if (!Object.keys(files).length) throw new Error(`harden: no engine found in ${path.join(resources, 'backend')}`);
    fs.writeFileSync(path.join(dir, 'integrity.json'), JSON.stringify({ files }));
    fs.rmSync(archive);
    await asar.createPackage(dir, archive);
    return { scrambled: done, engine: Object.keys(files) };
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

/** Write app.asar's header hash into the Windows exe, where Electron's integrity check reads it. */
async function embedAsarIntegrity(exe, archive) {
  const { NtExecutable, NtExecutableResource, Resource } = await import('resedit');
  const { getRawHeader } = require('@electron/asar');
  const hash = sha256(getRawHeader(archive).headerString);
  const pe = NtExecutable.from(fs.readFileSync(exe));
  const res = NtExecutableResource.from(pe);
  const info = Resource.VersionInfo.fromEntries(res.entries);
  const lang = (info[0] && info[0].getAllLanguagesForStringValues()[0]) || { lang: 1033, codepage: 1200 };
  res.entries = res.entries.filter((e) => !(String(e.type).toUpperCase() === 'INTEGRITY' && String(e.id).toUpperCase() === 'ELECTRONASAR'));
  const bin = Buffer.from(JSON.stringify([{ file: 'resources\\app.asar', alg: 'SHA256', value: hash }]), 'utf-8');
  res.entries.push({ type: 'INTEGRITY', id: 'ELECTRONASAR', bin: bin.buffer.slice(bin.byteOffset, bin.byteOffset + bin.length),
    lang: lang.lang, codepage: lang.codepage });
  res.outputResource(pe);
  fs.writeFileSync(exe, Buffer.from(pe.generate()));
  return hash;
}

/**
 * Seal the Windows exe (asar integrity + fuses) only when the build gets signed afterwards. Sealing changes the
 * exe's bytes, and Windows' Smart App Control blocks an unsigned exe it has never seen: measured 2026-10-30 on the
 * user's laptop (SAC on), the sealed Lunar.exe was refused (Code Integrity event 3077) while the untouched one — the
 * same bytes as Electron's electron.exe — ran. Signed: the Microsoft Store (appx/msix, Microsoft signs it), a
 * code-signing certificate (CSC_LINK / WIN_CSC_LINK), or MRSOLIS_SEAL_EXE=1. MRSOLIS_SEAL_EXE=0 always skips it.
 */
function sealWindowsExe(targets = []) {
  if (process.env.MRSOLIS_SEAL_EXE === '1') return true;
  if (process.env.MRSOLIS_SEAL_EXE === '0') return false;
  return targets.some((t) => ['appx', 'msix'].includes(String(t && t.name).toLowerCase()))
    || !!process.env.CSC_LINK || !!process.env.WIN_CSC_LINK;
}

async function harden(appOutDir, platform, exeName, targets = []) {
  const resources = platform === 'darwin' || platform === 'mas'
    ? path.join(appOutDir, `${exeName}.app`, 'Contents', 'Resources') : path.join(appOutDir, 'resources');
  const done = await hardenAsar(resources);
  console.log(`  • scrambled  ${done.scrambled.join(', ')}; engine fingerprinted: ${done.engine.join(', ')}`);
  if (platform === 'darwin' || platform === 'mas') {
    console.log('  • fuses: skipped on macOS (flipping them needs the app re-signed)');
    return;
  }
  const exe = path.join(appOutDir, platform === 'win32' ? `${exeName}.exe` : exeName);
  if (platform === 'win32' && !sealWindowsExe(targets)) {
    console.log(`  • ${path.basename(exe)} left as Electron's own (an unsigned build: Smart App Control would block a changed exe)`);
    return;
  }
  if (platform === 'win32') {
    const hash = await embedAsarIntegrity(exe, path.join(resources, 'app.asar'));
    console.log(`  • app.asar integrity written into ${path.basename(exe)} (${hash.slice(0, 12)}…)`);
    console.log(`  • fuses set  ${path.basename(exe)}: ${flipFuses(exe)}`);
  } else {
    // Linux reads no integrity resource: keep the fuse off there, or Electron would stop for want of a hash
    console.log(`  • fuses set  ${path.basename(exe)}: ${flipFuses(exe, { ...FUSES, 4: '0' })}`);
  }
}

module.exports = async function afterPack(context) {
  const platform = context.electronPlatformName;
  const exeName = platform === 'win32' || platform === 'darwin' || platform === 'mas'
    ? context.packager.appInfo.productFilename : context.packager.executableName;
  await harden(context.appOutDir, platform, exeName, context.targets || []);
};
Object.assign(module.exports, { flipFuses, obfuscate, engineFiles, hardenAsar, embedAsarIntegrity, sealWindowsExe, harden });
