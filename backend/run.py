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


def _no_power_throttling() -> None:
    """Windows 11 treats a process with no window as background work and, on battery, runs it
    on the slow efficiency cores ("EcoQoS"). That made every spoken sentence take ~4.5 s
    instead of ~0.6 s (measured 2026-10-17 on an i5-13420H) — and the tutor model runs here
    too. Opt out: this process does the student's interactive work."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class _State(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                        ("StateMask", wintypes.ULONG)]

        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetProcessInformation.restype = wintypes.BOOL
        state = _State(1, 0x1, 0x0)    # execution-speed throttling: we decide, and it's off
        k32.SetProcessInformation(k32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state))
    except Exception:
        pass


def _quit_with_parent() -> None:
    """Exit when the desktop app that started us is gone (closed, crashed or killed), so a
    backend holding the models in memory is never left running in the background."""
    ppid = os.environ.get("LUNAR_PARENT_PID")
    if not ppid or not ppid.isdigit():
        return
    import threading
    import time
    pid = int(ppid)

    def alive() -> bool:
        if sys.platform == "win32":
            import ctypes
            k32 = ctypes.WinDLL("kernel32")
            k32.OpenProcess.restype = ctypes.c_void_p
            h = k32.OpenProcess(0x00100000, False, pid)          # SYNCHRONIZE
            if not h:
                return False
            try:
                return k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102   # still running
            finally:
                k32.CloseHandle(ctypes.c_void_p(h))
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def watch():
        while True:
            time.sleep(2)
            if not alive():
                os._exit(0)

    threading.Thread(target=watch, daemon=True, name="lunar-parent-watch").start()


def _keep_output(data_dir: str) -> None:
    """The installed backend is a windowed program (no console). Started with nowhere to write — no pipes from the
    desktop shell — Python leaves sys.stdout / sys.stderr as None, and uvicorn's log setup calls
    sys.stdout.isatty(): the backend died before it served anything ("Unable to configure formatter 'default'",
    reported by students, 2026-11-03). Write to MrSOLIS's engine log instead (<data>/logs/engine.log, where the
    desktop shell also keeps what the backend says), or to nowhere."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = None
    if data_dir:
        try:
            os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)
            stream = open(os.path.join(data_dir, "logs", "engine.log"), "a", encoding="utf-8", errors="replace",
                          buffering=1)
        except OSError:
            stream = None
    if stream is None:
        try:
            stream = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            return                         # uvicorn is still told not to ask about colours (main); print() skips None
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> None:
    _no_power_throttling()
    _quit_with_parent()
    data_dir = os.environ.get("LUNAR_DATA_DIR") or ""
    _keep_output(data_dir)
    try:
        from backend import gate
    except ModuleNotFoundError:
        import gate  # frozen layout where `backend` isn't a top package
    # The installed backend serves only a licensed computer (backend/gate.py): started by hand without MrSOLIS's
    # licence it stops here, and it always listens on this computer only — never the network.
    frozen = bool(getattr(sys, "frozen", False))
    if gate.required() and not (data_dir and gate.licensed(data_dir)):
        if sys.stderr:                     # None when started by hand (no console in the installed app)
            sys.stderr.write("MrSOLIS isn't activated on this computer. Open MrSOLIS to activate it.\n")
        sys.exit(3)
    import uvicorn
    try:
        from backend.main import app
    except ModuleNotFoundError:
        from main import app  # frozen layout where `backend` isn't a top package

    host = "127.0.0.1" if frozen else os.environ.get("LUNAR_HOST", "127.0.0.1")
    port = int(os.environ.get("LUNAR_PORT", "8000"))
    # no colours: the output goes to a pipe or a log file, and asking a missing console about them crashed (above)
    uvicorn.run(app, host=host, port=port, log_level="warning", use_colors=False)


if __name__ == "__main__":
    main()
