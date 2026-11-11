#!/usr/bin/env python3
"""
Download the GGUF models Lunar bundles, into ../models/.

Run this ONCE before building the desktop app — the files it pulls get packaged
straight into the installer, so the end user never downloads anything.

    python scripts/fetch_models.py

Models (all public, no token):
    • Qwen2.5-1.5B-Instruct  (chat)   — Q4_K_M, ~1.1 GB
    • nomic-embed-text-v1.5  (embed)  — Q4_K_M, ~85 MB
    • voice, into models/voice/ (sherpa-onnx releases):
        NVIDIA Parakeet TDT 110M English (hearing, CC BY 4.0)   — ~108 MB
        Silero VAD (when the student talks, MIT)                — ~0.6 MB
        Supertonic 2 (speaking, male voice, OpenRAIL-M)         — ~85 MB

Override a URL/filename with env vars LUNAR_CHAT_GGUF_URL / LUNAR_EMBED_GGUF_URL
if Hugging Face ever renames a file.
"""

import os
import sys
import tarfile
import urllib.request

# Windows consoles default to cp1252 and choke on non-ASCII output; force UTF-8 so
# the progress glyphs never crash the download (this also bites the Windows CI box).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.normpath(os.path.join(HERE, "..", "models"))

HF = "https://huggingface.co"
MODELS = [
    {
        "name": "Qwen2.5-1.5B-Instruct (chat)",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "url": os.environ.get(
            "LUNAR_CHAT_GGUF_URL",
            f"{HF}/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        ),
    },
    {
        "name": "nomic-embed-text-v1.5 (embeddings)",
        "filename": "nomic-embed-text-v1.5.Q4_K_M.gguf",
        "url": os.environ.get(
            "LUNAR_EMBED_GGUF_URL",
            f"{HF}/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf",
        ),
    },
]

# Voice (backend/voice.py). Archives are unpacked into models/voice/<name>/.
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
VOICE_DIR = os.path.join(MODELS_DIR, "voice")
VOICE = [
    {"name": "Parakeet TDT 110M English (hearing)",
     "dest": "sherpa-onnx-nemo-parakeet_tdt_transducer_110m-en-36000-int8",
     "url": f"{SHERPA}/asr-models/sherpa-onnx-nemo-parakeet_tdt_transducer_110m-en-36000-int8.tar.bz2"},
    {"name": "Silero VAD (turn-taking)", "dest": "silero_vad.onnx",
     "url": f"{SHERPA}/asr-models/silero_vad.onnx"},
    {"name": "Supertonic 2 (voice)", "dest": "sherpa-onnx-supertonic-tts-int8-2026-03-06",
     "url": f"{SHERPA}/tts-models/sherpa-onnx-supertonic-tts-int8-2026-03-06.tar.bz2"},
]


def fetch_voice() -> int:
    os.makedirs(VOICE_DIR, exist_ok=True)
    failures = 0
    for m in VOICE:
        dest = os.path.join(VOICE_DIR, m["dest"])
        if os.path.exists(dest):
            print(f"✓ {m['name']} — already present")
            continue
        print(f"↓ {m['name']}\n    {m['url']}")
        try:
            if m["url"].endswith(".tar.bz2"):
                archive = os.path.join(VOICE_DIR, os.path.basename(m["url"]))
                _download(m["url"], archive)
                with tarfile.open(archive, "r:bz2") as tf:
                    tf.extractall(VOICE_DIR, filter="data")     # no links / paths outside the folder
                os.remove(archive)
            else:
                _download(m["url"], dest)
            print(f"✓ saved {m['dest']}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"\n✗ failed: {exc}")
    return failures


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024.0


def _download(url: str, dest: str) -> None:
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "lunar-fetch/1.0"})
    with urllib.request.urlopen(req) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    sys.stdout.write(f"\r    {pct:3d}%  {_human(done)} / {_human(total)}   ")
                else:
                    sys.stdout.write(f"\r    {_human(done)}   ")
                sys.stdout.flush()
    os.replace(tmp, dest)
    sys.stdout.write("\n")


def main() -> int:
    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"Downloading Lunar models into {MODELS_DIR}\n")
    failures = 0
    # --voice: only what the installer ships since MrSOLIS 3.0.0. The two GGUFs are Lunar 1's built-in model and
    # search model, kept for the text-only "Classic" mode in dev (needs llama-cpp-python); students use a brain.
    for m in ([] if "--voice" in sys.argv else MODELS):
        dest = os.path.join(MODELS_DIR, m["filename"])
        if os.path.isfile(dest) and os.path.getsize(dest) > 1_000_000:
            print(f"✓ {m['name']} — already present ({_human(os.path.getsize(dest))})")
            continue
        print(f"↓ {m['name']}\n    {m['url']}")
        try:
            _download(m["url"], dest)
            print(f"✓ saved {m['filename']} ({_human(os.path.getsize(dest))})")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"\n✗ failed: {exc}\n  Set the URL env var and retry, or download it by hand into {MODELS_DIR}.")
    failures += fetch_voice()
    print()
    if failures:
        print(f"{failures} model(s) failed. MrSOLIS needs them all (voice ones for the mic, Read aloud and Interactive mode).")
        return 1
    print("All models ready. You can now build the desktop app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
