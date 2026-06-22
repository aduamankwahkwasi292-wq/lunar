# Building the Lunar desktop app

Lunar ships as a **single double-click installer** per OS, with the AI models
(Qwen2.5-1.5B + nomic-embed) **bundled inside** and run on-device via **llama.cpp**.
The end user installs and runs it — **no Python, no Node, no Ollama, no downloads,
no setup**.

```
┌──────────────────────────────────────────────────────────────┐
│  Electron shell (desktop/)                                     │
│   • picks a free port, spawns the backend, shows a splash      │
│   • loads the UI the backend serves, kills it on quit          │
│                                                                │
│   └── lunar-backend  (PyInstaller binary, dist/lunar-backend)  │
│         FastAPI + PyMuPDF + RapidOCR + sympy + the frontend    │
│         └── llama.cpp (llama-cpp-python) runs the GGUF models  │
│               models/  ← bundled as Electron extraResources    │
└──────────────────────────────────────────────────────────────┘
```

The runtime LLM client is `backend/local_llm.py`. It defaults to the in-process
**llama.cpp** backend and falls back to Ollama only when you're developing without
the GGUFs present (`LUNAR_LLM_BACKEND=auto`).

---

## Prerequisites (on the machine doing the build)

- **Python 3.10+** and `pip`
- **Node.js LTS 18+** (`node`, `npm`)
- A C/C++ toolchain is only needed if `pip` can't find a prebuilt
  `llama-cpp-python` wheel (it usually can — see below).
- ~5 GB free disk for the build.

> ⚠️ **Build on each target OS.** electron-builder cannot make a macOS `.dmg` from
> Windows, etc. Build Windows on Windows, macOS on macOS, Linux on Linux — or use
> CI (GitHub Actions `runs-on: [windows-latest, macos-latest, ubuntu-latest]`).

---

## One-time setup

```bash
# 1. Python deps (incl. pyinstaller)
pip install -r requirements.txt

# 2. (Distribution) Build llama.cpp as a PORTABLE binary so the installer runs on
#    ANY CPU, not just yours. A -march=native / AVX-512 wheel crashes with
#    "illegal instruction" (Windows 0xc000001d) on older machines.
#    macOS:
CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_METAL=OFF" \
  pip install --force-reinstall --no-binary llama-cpp-python "llama-cpp-python>=0.3.2"
#    Windows / Linux (x86-64):
CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_AVX2=ON -DGGML_AVX512=OFF -DGGML_FMA=ON -DGGML_F16C=ON" \
  pip install --force-reinstall --no-binary llama-cpp-python "llama-cpp-python>=0.3.2"
#    (For quick LOCAL testing only, a prebuilt wheel is fine:
#       pip install "llama-cpp-python>=0.3.2" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu )

# 3. Download the GGUF models into ./models  (~1.2 GB, one time)
python scripts/fetch_models.py
```

> The CI workflow already does the portable build for you — this manual step is
> only for building installers on your own machine.

## Build the installer

```bash
python scripts/build_desktop.py
```

That freezes the backend (`dist/lunar-backend/`), then runs electron-builder.
Output lands in **`desktop/release/`**:

| OS      | Artifact                       |
|---------|--------------------------------|
| Windows | `Lunar-Setup-1.0.0.exe` (NSIS) |
| macOS   | `Lunar-1.0.0.dmg`              |
| Linux   | `Lunar-1.0.0.AppImage`, `.deb` |

Ship that file. The user double-clicks it and Lunar just works.

---

## Build all three automatically (CI)

`.github/workflows/release.yml` builds Windows + macOS + Linux installers on a
matrix runner and attaches them to the GitHub Release — no local building needed.

1. Push this repo to GitHub.
2. Create a Release (e.g. tag `v1.0.0`) and **Publish** it.
3. The workflow builds on `windows-latest`, `macos-latest`, `ubuntu-latest` and
   uploads `Lunar-Setup-*.exe`, `Lunar-*.dmg`, `Lunar-*.AppImage`, `Lunar-*.deb`
   straight onto that release.

It installs the prebuilt llama.cpp CPU wheel, **caches the ~1.2 GB models** between
runs, freezes the backend, and runs electron-builder per-OS. Builds are unsigned
(`CSC_IDENTITY_AUTO_DISCOVERY=false`); add code-signing/notarization secrets later
if you want signed installers. `workflow_dispatch` lets you run it manually (it
then uploads the installers as workflow artifacts instead of to a release).

---

## Run in development (no packaging)

```bash
# Backend (uses Ollama if no GGUFs are in ./models, else llama.cpp)
python -m backend.run                 # serves http://127.0.0.1:8000

# Electron pointing at the dev backend
cd desktop && npm install && npm start
```

`npm start` runs `desktop/main.js`, which in dev spawns `python -m backend.run`
from the repo and loads the UI. Set `LUNAR_PYTHON` if your interpreter isn't
`python`/`python3` on PATH.

---

## GPU (optional, later)

Builds are CPU-only by default for maximum "it just works" compatibility. To make
a GPU build, install a CUDA/Metal `llama-cpp-python` wheel and set
`LUNAR_N_GPU_LAYERS` (e.g. `35`) in `desktop/main.js`'s spawn env.

## Troubleshooting

- **"Illegal instruction" / `0xc000001d` on launch** — the llama.cpp binary was
  built for a newer CPU than the user's. Rebuild it portably with
  `CMAKE_ARGS="-DGGML_NATIVE=OFF …"` (see step 2 above). This is why CI builds from
  source instead of using a generic prebuilt wheel.
- **"No chat GGUF found"** — `models/` is empty; run `python scripts/fetch_models.py`.
- **Backend won't start in the packaged app** — run the frozen binary directly
  (`dist/lunar-backend/lunar-backend`) to see its logs; check `LUNAR_MODEL_DIR`.

## Swapping models

Drop any chat GGUF whose name contains `qwen`/`instruct` and any embedding GGUF
whose name contains `nomic`/`embed` into `models/` — `local_llm.py` auto-discovers
them. Override explicitly with `LUNAR_CHAT_GGUF` / `LUNAR_EMBED_GGUF`.
