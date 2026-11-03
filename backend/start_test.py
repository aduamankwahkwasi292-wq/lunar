"""The backend must start for every student (MrSOLIS 3.0.0–3.0.1 didn't, 2026-11-03):

  1. Started with nowhere to write (no console, no pipes: sys.stdout / sys.stderr are None), uvicorn's log setup
     called sys.stdout.isatty() and the backend died: "Unable to configure formatter 'default'".
  2. A new install has no brain until the student downloads one, and the installed app's /api/health then asked
     Ollama (dev machines only) — seconds per answer, and the desktop shell waited for a ready brain, so MrSOLIS
     never opened: "The Lunar engine did not start in time".

    python -m backend.start_test

Starts a real backend with no standard handles (pythonw.exe, like the installed windowed backend) on a throwaway
data folder; it never touches the student's own data. scripts/smoke_packaged.py checks the installed app itself.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "start-test"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def check_no_streams(data: str) -> str:
    """run._keep_output gives a backend with no streams the engine log, and uvicorn's log setup then works."""
    from . import run
    import uvicorn
    saved = sys.stdout, sys.stderr
    try:
        sys.stdout = sys.stderr = None
        run._keep_output(data)
        if sys.stdout is None or sys.stderr is None:
            return "no stream was given"
        uvicorn.Config(app=lambda *a: None, log_level="warning")       # the default colours: asks isatty()
        uvicorn.Config(app=lambda *a: None, log_level="warning", use_colors=False)
        print("start_test: written to the engine log", file=sys.stderr)
        sys.stderr.flush()
    except Exception as e:  # noqa: BLE001 - the failure is the finding
        return f"{type(e).__name__}: {e}"
    finally:
        log_stream = sys.stdout
        sys.stdout, sys.stderr = saved
        if log_stream not in saved and log_stream is not None:
            log_stream.close()
    log = os.path.join(data, "logs", "engine.log")
    if not os.path.isfile(log) or "written to the engine log" not in open(log, encoding="utf-8").read():
        return "nothing reached logs/engine.log"
    return ""


def check_health_without_brain(data: str) -> str:
    """The installed app's /api/health answers at once when no brain is downloaded, and says so."""
    os.environ["LUNAR_DATA_DIR"] = data
    os.environ["LUNAR_LLM_BACKEND"] = "ollama"            # what "auto" becomes in the installed app (no llama_cpp)
    from . import local_llm
    sys.frozen = True                                      # the installed app's branch
    try:
        t0 = time.time()
        h = asyncio.run(local_llm.health())
        took = time.time() - t0
    finally:
        del sys.frozen
    if took > 1:
        return f"took {took:.1f} s"
    if h.get("ok") or "No brain is downloaded yet" not in (h.get("error") or ""):
        return f"answered {h}"
    return ""


def check_real_start(data: str) -> str:
    """A real backend with no standard handles answers /api/health."""
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(exe):
        return f"no pythonw.exe next to {sys.executable}"
    port = _free_port()
    env = dict(os.environ, LUNAR_HOST="127.0.0.1", LUNAR_PORT=str(port), LUNAR_DATA_DIR=data, LUNAR_TOKEN=TOKEN,
               LUNAR_PARENT_PID=str(os.getpid()), LUNAR_LLM_BACKEND="auto")
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESTDHANDLES          # ...and every handle left empty
    proc = subprocess.Popen([exe, "-m", "backend.run"], cwd=ROOT, env=env, startupinfo=si, close_fds=True)
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            if proc.poll() is not None:
                return f"the backend stopped (code {proc.returncode})"
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={"x-mrsolis": TOKEN})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(req, timeout=10) as r:
                    json.loads(r.read())
                return ""
            except OSError:
                time.sleep(0.5)
        return "no answer in 120 s"
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)


def main() -> int:
    if sys.platform != "win32":
        print("start_test: Windows only (the installed backend there has no console)")
        return 0
    bad = 0
    for name, check in (("no streams", check_no_streams), ("health without a brain", check_health_without_brain),
                        ("real start, no handles", check_real_start)):
        with tempfile.TemporaryDirectory(prefix="mrsolis-start-test-", ignore_cleanup_errors=True) as data:
            problem = check(data)
        print(f"{'ok  ' if not problem else 'FAIL'} {name}{': ' + problem if problem else ''}")
        bad += bool(problem)
    print(f"start test: {3 - bad}/3 right")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
