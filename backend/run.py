"""
Lunar backend launcher.

Single entrypoint used by BOTH the desktop app (the frozen sidecar binary spawns
this) and local dev. Reads the host/port the desktop shell picked from the
environment so Electron and the backend always agree on the address.

    LUNAR_HOST  (default 127.0.0.1)
    LUNAR_PORT  (default 8000)
    LUNAR_MODEL_DIR / LUNAR_DATA_DIR  are set by the shell in production.
"""

import os
import sys

# Make `backend.*` importable no matter how this is launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    import uvicorn
    try:
        from backend.main import app
    except ModuleNotFoundError:
        from main import app  # frozen layout where `backend` isn't a top package

    host = os.environ.get("LUNAR_HOST", "127.0.0.1")
    port = int(os.environ.get("LUNAR_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
