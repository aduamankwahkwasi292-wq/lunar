# Releasing Lunar (so your friends can download it)

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

## Notes

- The installers are **unsigned**. For warning-free installs later, add Apple
  notarization + Windows code-signing secrets to the workflow.
- The first CI run downloads the ~1.2 GB models and caches them, so re-runs are
  faster.
- Cut a new version anytime: `gh release create v1.0.1 --generate-notes` (or draft
  it on the website). The matrix rebuilds and attaches fresh installers.
