"""
Fetch MrSOLIS 3's runtime programs for this platform into runtime/: the AI engine that runs the brain
(llama.cpp's llama-server, b11721 CPU build), FFmpeg for videos (LGPL "shared" build, n9.0.2) and Imagine's
picture engine (stable-diffusion.cpp's sd-cli, master-1104-5dcfa79 CPU build — Windows only so far).

    python scripts/fetch_runtime.py [--dest runtime] [--only llama.cpp,ffmpeg,sd.cpp]

Pinned downloads, each checked against its SHA-256 before anything is unpacked. The release build
(.github/workflows/release.yml) runs this before packaging; desktop/package.json ships runtime/llama.cpp,
runtime/ffmpeg and runtime/sd.cpp as extraResources, where backend/brain.py, backend/video.py and
backend/imagine.py look for them. The picture engine ships inside the app (17 MB zipped) rather than downloading
with the picture model: a program downloaded later isn't covered by the Store package's signature, so Smart App
Control would block it.
Kept in git: runtime/ffmpeg/README-MrSOLIS.txt and COPYING.GPLv3.txt (the LGPL v3 builds on the GPL v3 text).
macOS: there is no LGPL FFmpeg build pinned here, so videos need an ffmpeg on the PATH there.
"""
import argparse
import hashlib
import io
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

LLAMA = "https://github.com/ggml-org/llama.cpp/releases/download/b11721/"
FFMPEG = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-24-13-02/"
SDCPP = "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-1104-5dcfa79/"
PINS = {
    "win32": {
        "llama.cpp": (LLAMA + "llama-b11721-bin-win-cpu-x64.zip",
                      "19f5a91cfbd906fadfb36975a65a0c165c7db1a533d5db129dfa0a533dfdeaa1"),
        "ffmpeg": (FFMPEG + "ffmpeg-n9.0.2-35-g9a9b70bb8c-win64-lgpl-shared-9.0.zip",
                   "fb771d872989dba5d96621a840194362202426e882814a0d5e7eddd8387908d3"),
        "sd.cpp": (SDCPP + "sd-master-5dcfa79-bin-win-cpu-x64.zip",
                   "b5297bea319d6247e95e9a6834c190047ab0a493a29539b41f217e9cc440025a"),
    },
    "linux": {
        "llama.cpp": (LLAMA + "llama-b11721-bin-ubuntu-x64.tar.gz",
                      "68c7a4dfb6a53e607b73c00c839bfc81c55141cd0a7697c0252e634190647c2f"),
        "ffmpeg": (FFMPEG + "ffmpeg-n9.0.2-35-g9a9b70bb8c-linux64-lgpl-shared-9.0.tar.xz",
                   "c9c697e798b0e677b7e673667b8436d62ff4d795155648b54ebe7e849e2667c0"),
    },
    "darwin-arm64": {
        "llama.cpp": (LLAMA + "llama-b11721-bin-macos-arm64.tar.gz",
                      "2ace55512ee1ab4e2703f80c135c2a92d40d3367a5b3a98d21b103ffa7f0eb82"),
    },
    "darwin-x86_64": {
        "llama.cpp": (LLAMA + "llama-b11721-bin-macos-x64.tar.gz",
                      "de3e409d44a9130f8e863975c13693f047b1c657180a94485464eb7cd5747579"),
    },
}
EXE = ".exe" if sys.platform == "win32" else ""


def fetch(url, sha):
    print(f"  downloading {url.rsplit('/', 1)[-1]}")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            break
        except OSError:
            if attempt == 3:
                raise
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        raise SystemExit(f"SHA-256 mismatch for {url}: {got}")
    return data


def unpack(data, url, into):
    if url.endswith(".zip"):
        zipfile.ZipFile(io.BytesIO(data)).extractall(into)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(into, filter="data")


def find_dir(root, name):
    for d, _dirs, files in os.walk(root):
        if name in files:
            return d
    raise SystemExit(f"{name} not found in the download")


def llama(pin, dest):
    url, sha = pin
    with tempfile.TemporaryDirectory() as tmp:
        unpack(fetch(url, sha), url, tmp)
        src = find_dir(tmp, "llama-server" + EXE)
        out = os.path.join(dest, "llama.cpp")
        os.makedirs(out, exist_ok=True)
        for f in os.listdir(src):
            if os.path.isfile(os.path.join(src, f)):
                shutil.copy2(os.path.join(src, f), os.path.join(out, f))
    print(f"  llama.cpp -> {out}")


def ffmpeg(pin, dest):
    url, sha = pin
    out = os.path.join(dest, "ffmpeg")
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        unpack(fetch(url, sha), url, tmp)
        bin_dir = find_dir(tmp, "ffmpeg" + EXE)
        top = os.path.dirname(bin_dir)
        if sys.platform == "win32":                  # the programs and their DLLs side by side, no ffplay
            for f in os.listdir(bin_dir):
                if f.endswith(".dll") or f in ("ffmpeg.exe", "ffprobe.exe"):
                    shutil.copy2(os.path.join(bin_dir, f), os.path.join(out, f))
        else:                                        # bin/ + lib/: the programs find their libraries via ../lib
            os.makedirs(os.path.join(out, "bin"), exist_ok=True)
            for f in ("ffmpeg", "ffprobe"):
                shutil.copy2(os.path.join(bin_dir, f), os.path.join(out, "bin", f))
            shutil.copytree(os.path.join(top, "lib"), os.path.join(out, "lib"), dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("*.a", "pkgconfig", "*.def"))
        shutil.copy2(os.path.join(top, "LICENSE.txt"), os.path.join(out, "LICENSE.txt"))
    print(f"  ffmpeg -> {out}")


def sd_cpp(pin, dest):
    """sd-cli and the libraries beside it (ggml's CPU variants, picked at run time; the WebP/WebM writers it links);
    not sd-server or its start scripts. Its licence texts (*.txt) come along."""
    url, sha = pin
    out = os.path.join(dest, "sd.cpp")
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        unpack(fetch(url, sha), url, tmp)
        src = find_dir(tmp, "sd-cli" + EXE)
        for f in os.listdir(src):
            p = os.path.join(src, f)
            if os.path.isfile(p) and not f.startswith(("sd-server", "start-server")):
                shutil.copy2(p, os.path.join(out, f))
    print(f"  sd.cpp -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime"))
    ap.add_argument("--only", default="", help="comma-separated parts to fetch: llama.cpp, ffmpeg, sd.cpp (default: all)")
    a = ap.parse_args()
    want = {p.strip() for p in a.only.split(",") if p.strip()} or {"llama.cpp", "ffmpeg", "sd.cpp"}
    key = sys.platform if sys.platform in PINS else f"darwin-{platform.machine()}"
    pins = PINS.get(key)
    if not pins:
        raise SystemExit(f"no runtime pinned for {key}")
    print(f"MrSOLIS runtime for {key} -> {a.dest}")
    if "llama.cpp" in want:
        llama(pins["llama.cpp"], a.dest)
    if "ffmpeg" in want:
        if "ffmpeg" in pins:
            ffmpeg(pins["ffmpeg"], a.dest)
        else:
            print("  ffmpeg: none pinned for this platform (videos use an ffmpeg on the PATH)")
    if "sd.cpp" in want:
        if "sd.cpp" in pins:
            sd_cpp(pins["sd.cpp"], a.dest)
        else:
            print("  sd.cpp: none pinned for this platform (Imagine can't paint here)")


if __name__ == "__main__":
    main()
