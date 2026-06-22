#!/usr/bin/env python3
"""
Build the Lunar desktop installer for the CURRENT operating system.

    python scripts/build_desktop.py

Steps:
    1. check the GGUF models are present (run fetch_models.py first if not),
    2. freeze the Python backend with PyInstaller  -> dist/lunar-backend/,
    3. npm install + electron-builder in desktop/   -> desktop/release/<installer>.

You must run this ON each target OS (or in CI): a Windows .exe builds on Windows,
a macOS .dmg on macOS, a Linux .AppImage/.deb on Linux. electron-builder cannot
cross-compile a Mac app from Windows/Linux.
"""

import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
MODELS = os.path.join(ROOT, "models")
DESKTOP = os.path.join(ROOT, "desktop")


def run(cmd, cwd=None):
    print(f"\n$ {' '.join(cmd)}  (cwd={cwd or ROOT})")
    subprocess.check_call(cmd, cwd=cwd or ROOT)


def have_models() -> bool:
    return len(glob.glob(os.path.join(MODELS, "**", "*.gguf"), recursive=True)) >= 2


def npm() -> str:
    return "npm.cmd" if sys.platform == "win32" else "npm"


def main() -> int:
    if not have_models():
        print("✗ No GGUF models found in ./models")
        print("  Run:  python scripts/fetch_models.py   (then re-run this build)")
        return 1

    print("▶ Freezing the backend with PyInstaller…")
    run([sys.executable, "-m", "PyInstaller", "lunar-backend.spec", "--noconfirm"])

    out = os.path.join(ROOT, "dist", "lunar-backend")
    if not os.path.isdir(out):
        print(f"✗ Expected PyInstaller output at {out} — build failed.")
        return 1
    print(f"✓ Backend frozen at {out}")

    if shutil.which(npm()) is None:
        print("✗ npm not found — install Node.js LTS (https://nodejs.org) and re-run.")
        return 1

    print("▶ Installing Electron deps…")
    run([npm(), "install"], cwd=DESKTOP)
    print("▶ Building the installer…")
    run([npm(), "run", "dist"], cwd=DESKTOP)

    rel = os.path.join(DESKTOP, "release")
    print(f"\n✓ Done. Installer(s) in {rel}")
    for f in sorted(glob.glob(os.path.join(rel, "*"))):
        if os.path.isfile(f):
            print("   •", os.path.basename(f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
