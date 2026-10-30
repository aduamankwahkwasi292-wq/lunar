"""
Compile the backend's licence check (backend/gate.py) to a native module for release builds (hardening, 2026-10-30).
A .py check can be read and edited inside the installed app; a compiled one can't, and main.js refuses an engine
whose compiled check was swapped (desktop/build/harden.js fingerprints it).

    python scripts/build_gate.py --release   # the release workflow, before PyInstaller: backend/gate.<tag>.pyd, and
                                             # gate.py moved aside so PyInstaller can only bundle the compiled one
    python scripts/build_gate.py --out DIR   # a test build somewhere else (dev runs keep using gate.py)

Needs Cython and a C compiler (MSVC on Windows: the GitHub runner has it; this laptop has Build Tools 2019).
"""
import argparse
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "backend", "gate.py")


def build(out_dir: str) -> str:
    from Cython.Build import cythonize
    from setuptools import Extension
    from setuptools.command.build_ext import build_ext
    from setuptools.dist import Distribution

    work = tempfile.mkdtemp(prefix="mrsolis-gate-")
    try:
        src = os.path.join(work, "gate.py")
        shutil.copy(GATE, src)
        ext = cythonize([Extension("gate", [src])], build_dir=work, quiet=True,
                        compiler_directives={"language_level": 3, "binding": False, "embedsignature": False})
        cmd = build_ext(Distribution({"name": "gate", "ext_modules": ext}))
        cmd.build_lib, cmd.build_temp = os.path.join(work, "lib"), os.path.join(work, "tmp")
        cmd.ensure_finalized()
        cmd.run()
        name = next(f for f in os.listdir(cmd.build_lib) if f.startswith("gate.") and f.endswith((".pyd", ".so")))
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, name)
        shutil.copy(os.path.join(cmd.build_lib, name), dst)
        return dst
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="put the compiled module here instead of backend/")
    ap.add_argument("--release", action="store_true", help="beside gate.py, and move gate.py aside (CI only)")
    args = ap.parse_args()
    if not args.out and not args.release:
        ap.error("say --release (CI) or --out DIR (a test build)")
    dst = build(args.out or os.path.dirname(GATE))
    if args.release:
        os.replace(GATE, GATE + ".src")
    print(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
