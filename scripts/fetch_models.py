#!/usr/bin/env python3
"""
Download the GGUF models Lunar bundles, into ../models/.

Run this ONCE before building the desktop app — the files it pulls get packaged
straight into the installer, so the end user never downloads anything.

    python scripts/fetch_models.py

Models (all public, no token, no voice models):
    • Qwen2.5-1.5B-Instruct  (chat)   — Q4_K_M, ~1.1 GB
    • nomic-embed-text-v1.5  (embed)  — Q4_K_M, ~85 MB

Override a URL/filename with env vars LUNAR_CHAT_GGUF_URL / LUNAR_EMBED_GGUF_URL
if Hugging Face ever renames a file.
"""

import os
import sys
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
    for m in MODELS:
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
    print()
    if failures:
        print(f"{failures} model(s) failed. Lunar needs both to run.")
        return 1
    print("All models ready. You can now build the desktop app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
