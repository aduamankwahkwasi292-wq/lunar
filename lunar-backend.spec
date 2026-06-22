# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Lunar backend sidecar.

Produces a self-contained one-folder binary (dist/lunar-backend/) that the
Electron app ships as a resource and spawns. Bundles the FastAPI app, the whole
frontend, and every native dep (PyMuPDF, NumPy, Pillow, RapidOCR/onnxruntime,
sympy, python-pptx, and the llama.cpp shared library).

Build (run from the project root, on EACH target OS):
    pip install -r requirements.txt pyinstaller
    pyinstaller lunar-backend.spec --noconfirm

NOTE: the GGUF models are NOT bundled here — they are shipped as Electron
extraResources and located at runtime via LUNAR_MODEL_DIR, so the backend binary
stays small and the same build works regardless of which models you ship.
"""

import os
from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = os.path.abspath(os.getcwd())

datas = []
binaries = []
hiddenimports = [
    "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
]

# Collect everything (code, data files, native libs) for the tricky packages.
for pkg in [
    "llama_cpp",            # the llama.cpp shared library + python bindings
    "rapidocr_onnxruntime", # OCR + bundled onnx models
    "onnxruntime",
    "fitz",                 # PyMuPDF
    "pptx",                 # python-pptx
    "sympy",
    "fastapi",
    "starlette",
    "anyio",
    "httpx",
    "PIL",
    "numpy",
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # a package may be absent on some platforms
        print(f"[lunar-backend.spec] skip collect_all({pkg}): {exc}")

# Ship the frontend (HTML/CSS/JS/images) inside the binary.
datas += [(os.path.join(PROJECT_ROOT, "frontend"), "frontend")]

block_cipher = None

a = Analysis(
    [os.path.join(PROJECT_ROOT, "backend", "run.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lunar-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # no flashing console window; Electron captures stdio
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="lunar-backend",
)
