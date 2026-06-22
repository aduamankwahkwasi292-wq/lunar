"""
One-time local model setup for Lunar AI.

Downloads the bundled Piper voice (if missing) and warms the faster-whisper
STT model so the first voice interaction is instant. Safe to run repeatedly —
it skips anything already present. Called by start.bat / start.sh.
"""

import os
import sys
import urllib.request

PIPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "piper")
PIPER_VOICE = "en_US-amy-medium"
PIPER_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_US/amy/medium/"
)
PIPER_FILES = [f"{PIPER_VOICE}.onnx", f"{PIPER_VOICE}.onnx.json"]


def download_piper():
    os.makedirs(PIPER_DIR, exist_ok=True)
    for fname in PIPER_FILES:
        dest = os.path.join(PIPER_DIR, fname)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"  [ok] Piper voice present: {fname}")
            continue
        url = PIPER_BASE + fname
        print(f"  [..] Downloading {fname} ...")
        try:
            urllib.request.urlretrieve(url, dest)
            print(f"  [ok] Saved {fname}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [!!] Could not download {fname}: {exc}")
            print("       Voice will fall back to the system speech engine.")
            return False
    return True


def warm_whisper():
    print("  [..] Preparing speech-to-text model (faster-whisper base)...")
    try:
        from faster_whisper import WhisperModel

        WhisperModel("base", device="cpu", compute_type="int8")
        print("  [ok] Speech-to-text model ready.")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [!!] Could not prepare Whisper model: {exc}")
        return False


if __name__ == "__main__":
    print("Setting up local voice models...")
    download_piper()
    warm_whisper()
    print("Done.")
    sys.exit(0)
