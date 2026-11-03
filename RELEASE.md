# Releasing MrSOLIS

## MrSOLIS 3 (from 3.0.0, 2026-10-30)

- **Where:** github.com/aduamankwahkwasi292-wq/lunar (public again since 2026-10-30). Installed copies read its
  releases for updates (`publish` in desktop/package.json), and the website's Download buttons point at its latest
  release (`Downloads\lunar\mrsolis-website`, served from the lunar-app repo's GitHub Pages).
- **Windows only.** The installer no longer carries Lunar 1's built-in model and search model (1.2 GB): students pick
  Speedy or Smarts on first start. Without them, "Find anything" matches words and slide numbers, not meaning.
- **GitHub Actions can't run** while the account is locked over billing (every job stops with "your account is locked
  due to a billing issue", even on public repos). Until that's cleared, build on the laptop:

### Building on this laptop

This folder is a git checkout of `lunar` since 2026-10-30 (`git status`, `git push`). Build from a clean copy so the
licence-check step (which moves gate.py aside) never touches the working folder:

```bash
# once: pip install pyinstaller "rapidocr-onnxruntime>=1.2.3"   (Cython and VS Build Tools 2019 are installed)
B=/c/Users/aduam/Downloads/lunar/build/src
git clone -q . "$B"                                    # the committed code only
cp -r models/voice "$B/models/"; cp -r runtime/llama.cpp runtime/ffmpeg "$B/runtime/"
cmd //c mklink /J "$(cygpath -w "$B/desktop/node_modules")" "$(cygpath -w "$PWD/desktop/node_modules")"
cd "$B" && python scripts/build_gate.py --release && python -m PyInstaller lunar-backend.spec --noconfirm
cd desktop && CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --win --publish never
```

Then check `desktop/release/` (the installer, its `.blockmap`, `latest.yml`) and publish them:

```bash
gh release create v3.0.1 --repo aduamankwahkwasi292-wq/lunar --draft --title "MrSOLIS 3.0.1" --notes "…" \
  release/Lunar-Setup-3.0.1.exe release/Lunar-Setup-3.0.1.exe.blockmap release/latest.yml
gh release edit v3.0.1 --repo aduamankwahkwasi292-wq/lunar --draft=false    # once all three are uploaded
```

Bump `version` in desktop/package.json first (`npm version 3.0.1 --no-git-tag-version`), commit and push, and tag
the release at that commit.

### Before publishing: test the package, not the build

A build that packs is not a build that works. 3.0.0 and 3.0.1 built, packed and uploaded fine and never opened for a
new student (2026-11-03): every test had started the app from a terminal, with a brain already copied into the test
profile, and the engine crashed or MrSOLIS waited for a brain the student could only download once it was open.
Smart App Control is off on this laptop since 2026-10-30, so the built app runs here. Upload as a **draft**, and
publish only when every stage passes:

| Stage | Check | Pass |
|---|---|---|
| builds | PyInstaller and electron-builder (above) | both finish |
| the code | `python -m backend.start_test` · `python -m backend.crib_test` | 3/3 · all right |
| installer → first launch → engine → brain → answer | in `build\src`: `python scripts/smoke_packaged.py desktop/release/Lunar-Setup-x.y.z.exe --licence ..\test-profile\licence.json --brains ..\test-profile` | every stage PASS |
| Store package | the same script with `--store` (next section) | PASS |
| a real install | the installer on another PC (no Python, no tools), then open MrSOLIS from the desktop icon | MrSOLIS opens, picks a brain, answers |

The script starts the app the way Windows does for a student (no console, a fresh profile with only a licence, no
brain) and the engine on its own with no standard handles; the brain stages use the test profile's Speedy / Smarts.
Copies stuck on a version that can't open never reach the update check (it runs once the engine is up), so a fix for
a start-up failure also needs students to download the installer again from the website.


### The Microsoft Store package (MrSOLIS-x.y.z.appx)

Identity is in desktop/package.json `build.appx` (from Partner Center → Product identity). electron-builder's own
makeappx fails on this laptop ("side-by-side configuration is incorrect"), so pack with the Windows SDK's:

```bash
cd desktop && CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --win appx --publish never   -c.electronDist=node_modules/electron/dist -c.directories.output=release-store   # stops at makeappx: expected
```

It leaves `release-store/__appx-x64/` with AppxManifest.xml and mapping.txt. In the manifest, set
MaxVersionTested to 10.0.19041.0. Then run, in PowerShell:
`& "C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\makeappx.exe" pack /o /f release-store\__appx-x64\mapping.txt /p release-store\MrSOLIS-x.y.z.appx`
Upload that file in Partner Center (Microsoft signs it; the Store version updates through the Store, not GitHub):
a new submission with the new package, whose version must be higher than the last one sent.

Test it first, inside its own package (Developer Mode is on, on this laptop), in PowerShell from `build\src\desktop`:

```powershell
$mk = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\makeappx.exe"
$t = (Resolve-Path ..\..).Path + "\appx-test"
& $mk unpack /p release-store\MrSOLIS-x.y.z.appx /d $t /o
Add-AppxPackage -Register "$t\AppxManifest.xml"
python ..\scripts\smoke_packaged.py "$t\app" --licence ..\..\test-profile\licence.json --store (Get-AppxPackage BehemothGroup.MrSOLIS).PackageFamilyName --store-exe "$t\app\Lunar.exe" --work ..\..\smoke-work
Remove-AppxPackage (Get-AppxPackage BehemothGroup.MrSOLIS).PackageFullName
```

Never open that test package from the Start menu: without `--user-data-dir` it would use (and change) the real
MrSOLIS profile in %APPDATA%\lunar-desktop.

---

## Lunar 1 (the original guide)

The repo is already committed on the `main` branch. Pushing it to GitHub and
publishing a Release triggers the CI matrix, which builds the **Windows, macOS,
and Linux** installers and attaches them to that Release automatically.

Pick ONE route.

---

## Route A — GitHub CLI (fewest clicks, recommended)

```powershell
# 1. Install the GitHub CLI, then CLOSE and REOPEN your terminal
winget install --id GitHub.cli -e

# 2. Log in (opens your browser)
gh auth login        # GitHub.com  →  HTTPS  →  Login with a web browser

# 3. From the project folder, create the PUBLIC repo and push it
cd "C:\Users\user\Desktop\MORFI\Lunar-ai-main\Lunar-ai-main"
gh repo create lunar --public --source=. --remote=origin --push

# 4. Publish the release that builds the installers
gh release create v1.0.0 --title "Lunar 1.0.0" --notes "Download the installer for your OS below."
```

Then watch it build and open the download page:

```powershell
gh run watch                       # ~15–30 min for all three
gh release view v1.0.0 --web       # the 3 installers are attached here
```

Send friends that page's URL.

---

## Route B — Website (no install)

1. Go to <https://github.com/new> → name it `lunar` → **Public** → **Create
   repository** (do NOT add a README/.gitignore).
2. Push:
   ```powershell
   cd "C:\Users\user\Desktop\MORFI\Lunar-ai-main\Lunar-ai-main"
   git remote add origin https://github.com/<your-username>/lunar.git
   git push -u origin main
   ```
   (A browser window may pop up to log in to GitHub — that's normal.)
3. On the repo page: **Releases** → **Draft a new release** → **Choose a tag** →
   type `v1.0.0` → **Create new tag** → **Publish release**.
4. Open the **Actions** tab — "Build Lunar installers" runs on all three OSes.
   When every job is green (~15–30 min), refresh the **Releases** page: the
   `.exe`, `.dmg`, `.AppImage`, and `.deb` are attached.
5. Share the release link.

---

## What your friends do

Download the file for their OS from the Releases page, then:

- **Windows** — run `Lunar-Setup-1.0.0.exe`. SmartScreen may warn (unsigned):
  **More info → Run anyway**.
- **macOS** — open `Lunar-1.0.0.dmg`, drag Lunar to Applications. First launch:
  **right-click the app → Open** (unsigned/not notarized).
- **Linux** — `chmod +x Lunar-1.0.0.AppImage && ./Lunar-1.0.0.AppImage`, or
  `sudo dpkg -i Lunar-1.0.0.deb`.

That's it — no Python, no Node, no Ollama, no model downloads. ~1.5–2 GB installer
(the models are inside). First launch takes a few seconds while the model loads.

---

## Shipping an update (so users auto-update)

The app checks your GitHub Releases on launch. When you publish a **newer** version, installed apps **ask first**:
*"MrSOLIS X is available. Downloading it uses up to N MB of internet data."* with Download / Not now / Skip this
version (`desktop/updates.js`, since 2026-10-26: students pay for their data). After the download: *"Restart now"*,
or it installs the next time they close the app. Users of builds older than this one still download by themselves.

1. Make your changes.
2. Bump the version in `desktop/package.json` (`"version": "1.0.1"`), commit, push.
3. Publish a new release with the **matching tag**:
   ```powershell
   gh release create v1.0.1 --title "Lunar 1.0.1" --notes "What's new…"
   ```
4. CI rebuilds all three OSes and uploads the new installers **plus** the update
   files (`latest.yml`, `latest-mac.yml`, `latest-linux.yml`, `.blockmap`).
5. Everyone's Lunar offers the update next time they open it. No re-sharing links.

> The tag version and `desktop/package.json` version must match (CI also syncs them
> for you). Auto-update only works for users already on a build that includes the
> updater — i.e. v1.0.0 onward.

## Licences (MrSOLIS 3 onward, 2026-10-26)

The installed app asks for a licence code (`MRS-XXXX-XXXX-XXXX`) before it opens, and checks it once a day when
online. The server and your admin tool are in `Downloads\lunar\licence-server` (its README has every step).

Before the **first** release with licences:

1. ~~Put the licence server online and set `SERVER` in `desktop/licence.js`~~ **Done 2026-10-27:**
   https://mrsolis-licence.jonsonwhocancreate.workers.dev (Cloudflare). The release workflow would fail if
   `SERVER` ever went back to the placeholder `licence.mrsolis.example`.
2. **People already on Lunar 1 get the update and then the activation screen.** Make their codes first, e.g. one
   shared tester code: `node admin.mjs new --kind tester --max 50 --note "Lunar testers"`, and send it to them
   with the update.
3. Back up `licence-server/keys/` somewhere that isn't the laptop.
4. **Selling inside MrSOLIS (US$1, paid as GHS 12 since 2026-10-29; GHS 35 before):** on since 2026-10-28, by **Mobile Money to 020 483 2725** (Telecel Cash · Janet
   Nartey). Each sale waits until you confirm it in MrSOLIS Licences → Payments (licence-server/README.md).
   Card payments online (Flutterwave or Paystack) aren't available yet. Flutterwave waitlisted us, and Paystack never
   sent its code. The code is ready: `licence-server/Set payment key.cmd` switches it on once a provider accepts you.
5. **Hardening (2026-10-29; CLAUDE.md "Hardening"):**
   - Deploy the licence server once more (`npx wrangler deploy` in licence-server) if it isn't live yet: it carries
     the request limits (the race fix went live on 2026-10-30).
   - The workflow's "Compile the licence check (Cython)" step must pass (scripts/build_gate.py --release).
   - In the build log, the packaging step (desktop/build/harden.js) prints `scrambled  main.js, licence.js,
     preload.js, updates.js; engine fingerprinted: backend/lunar-backend.exe,
     backend/_internal/backend/gate.cp311-win_amd64.pyd`. An unsigned build then prints `Lunar.exe left as Electron's
     own`. A signed build (Store or certificate) prints `app.asar integrity written into Lunar.exe` and
     `fuses set  Lunar.exe: 00001101`. If the step fails instead, check before releasing: Electron's fuse layout or
     PyInstaller's folder layout may have changed.
   - **Smart App Control:** Windows 11 PCs with it on block unsigned apps. They blocked the installed Lunar 1's
     engine on the owner's laptop (2026-10-06), so the unsigned installer won't run there. The free fix is the
     Microsoft Store (CLAUDE.md "Hardening").
   - Install the new build once and open it: it must reach the activation screen. A tampered app.asar or engine
     makes it refuse to start; that is intended.
   - The installed backend now refuses to start without the licence, and only MrSOLIS's own windows can reach it.

Selling: for every buyer, `node admin.mjs new --note "<name, payment ref>"` and send them the code. Refunds:
`admin.mjs refund` (the README). Licences can't be moved to another computer (for now).

## Notes

- The installers are **unsigned**. For warning-free installs later, add Apple
  notarization + Windows code-signing secrets to the workflow.
- The first CI run downloads the ~1.2 GB models and caches them, so re-runs are
  faster.
- Cut a new version anytime: `gh release create v1.0.1 --generate-notes` (or draft
  it on the website). The matrix rebuilds and attaches fresh installers.
