"""Release gate: does the PACKAGED MrSOLIS start for a new student? (Windows; run on the build laptop.)

MrSOLIS 3.0.0 and 3.0.1 built, packed and uploaded fine, and still never opened for a new student (2026-11-03):
every test before them launched the app from a terminal, with a brain already copied into the test profile. This
checks the exact files the installer lays down, started the way Windows starts them for a student, stage by stage:

  1. installer unpacks         the .exe holds Lunar.exe, the engine and app.asar
  2. engine, no console        lunar-backend.exe started with no standard handles answers /api/health
  3. first launch              Lunar.exe started like the Start menu does (no console, no handles), a fresh profile
                               with only a licence, no brain: the MrSOLIS window opens, no error box
  4. brain loads    (--brains) the engine loads a downloaded brain (Speedy / Smarts)
  5. answers        (--brains) a real question gets a real answer from it
  6. Store package  (--store)  the same first launch inside the registered Microsoft Store package

    python scripts/smoke_packaged.py desktop/release/Lunar-Setup-3.0.2.exe --licence ..\\build\\test-profile\\licence.json --brains ..\\build\\test-profile
    python scripts/smoke_packaged.py <unpacked app folder> --licence <licence.json> --store BehemothGroup.MrSOLIS_<id> --store-exe <layout>\\app\\Lunar.exe

The licence must be one made for this computer (a test profile's licence.json). Brains are linked in (a
junction), never copied. Nothing touches the student's own profile; everything it starts is closed by PID.
Exit code 0 only when every stage that ran passed.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
k32 = ctypes.WinDLL("kernel32")
user32 = ctypes.WinDLL("user32")
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = "smoke-test"


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def processes():
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    out = {}
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def tree(root):
    procs, keep, grew = processes(), {root}, True
    while grew:
        grew = False
        for pid, (ppid, _) in procs.items():
            if ppid in keep and pid not in keep:
                keep.add(pid)
                grew = True
    return {pid: procs[pid][1].lower() for pid in keep if pid in procs}


def windows_of(pids):
    found = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value in pids:
                n = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                found.append((pids[p.value], buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def kill_tree(root, extra=()):
    for pid in sorted(set(tree(root)) | set(extra), reverse=True):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def no_handles():
    """STARTUPINFO for a child with no standard handles at all: what Explorer gives a program it starts."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESTDHANDLES
    return si


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def clean_env(extra):
    """What a fresh Windows account has: no Python, no dev tools on PATH."""
    keep = ["SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "USERNAME",
            "USERDOMAIN", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "ProgramData", "ProgramFiles",
            "ProgramFiles(x86)", "ProgramW6432", "CommonProgramFiles", "PUBLIC", "ALLUSERSPROFILE",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS", "COMPUTERNAME"]
    env = {k: os.environ[k] for k in keep if k in os.environ}
    root = os.environ.get("SystemRoot", r"C:\Windows")
    env["PATH"] = ";".join([root + r"\system32", root, root + r"\System32\Wbem",
                            root + r"\System32\WindowsPowerShell\v1.0"])
    env.update(extra)
    return env


WORK = tempfile.gettempdir()          # --work: where throwaway profiles go


def profile(licence, brains_from=""):
    """A throwaway profile with this computer's licence and, if asked, the brains linked in."""
    prof = tempfile.mkdtemp(prefix="mrsolis-smoke-", dir=WORK)
    shutil.copy(licence, os.path.join(prof, "licence.json"))
    if brains_from:
        subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(prof, "brains"), os.path.join(brains_from, "brains")],
                       capture_output=True, check=True)
    return prof


def drop_profile(prof):
    link = os.path.join(prof, "brains")
    if os.path.isdir(link) and os.path.realpath(link) != os.path.abspath(link):
        os.rmdir(link)                                      # the junction only, never the brains in it
    if os.path.lexists(link) and os.path.realpath(link) != os.path.abspath(link):
        print(f"   (left {prof}: its brains link wouldn't go)")
        return
    shutil.rmtree(prof, ignore_errors=True)


def engine_log(prof):
    log = os.path.join(prof, "logs", "engine.log")
    return open(log, encoding="utf-8", errors="replace").read() if os.path.isfile(log) else ""


def get_json(port, path, timeout=10, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"x-mrsolis": TOKEN,
                                 "content-type": "application/json"}, data=json.dumps(body).encode() if body else None)
    with NOPROXY.open(req, timeout=timeout) as r:
        return r.read()


# ── the stages ─────────────────────────────────────────────────────────────────────────────────────────────────
def unpack(installer, dest):
    seven = os.path.join(ROOT, "desktop", "node_modules", "7zip-bin", "win", "x64", "7za.exe")
    subprocess.run([seven, "x", installer, f"-o{dest}", "-y"], capture_output=True, check=True)
    need = ["Lunar.exe", os.path.join("resources", "app.asar"), os.path.join("resources", "backend", "lunar-backend.exe")]
    missing = [n for n in need if not os.path.isfile(os.path.join(dest, n))]
    return ("missing " + ", ".join(missing)) if missing else ""


def start_engine(app_dir, prof):
    res = os.path.join(app_dir, "resources")
    exe = os.path.join(res, "backend", "lunar-backend.exe")
    port = free_port()
    env = clean_env({"LUNAR_HOST": "127.0.0.1", "LUNAR_PORT": str(port), "LUNAR_MODEL_DIR": os.path.join(res, "models"),
                     "LUNAR_DATA_DIR": prof, "LUNAR_PARENT_PID": str(os.getpid()), "LUNAR_TOKEN": TOKEN,
                     "LUNAR_LLM_BACKEND": "auto"})
    proc = subprocess.Popen([exe], cwd=os.path.dirname(exe), env=env, startupinfo=no_handles(), close_fds=True)
    return proc, port


def wait_health(proc, port, secs, want=lambda h: True):
    deadline, last = time.time() + secs, None
    while time.time() < deadline:
        if proc.poll() is not None:
            return None, f"the engine stopped (code {proc.returncode})"
        if any(t == "Unhandled exception in script" for _, t in windows_of(tree(proc.pid))):
            return None, "the engine crashed (Unhandled exception in script)"
        try:
            last = json.loads(get_json(port, "/api/health"))
            if want(last):
                return last, ""
        except (OSError, ValueError):
            pass
        time.sleep(1)
    return last, f"not ready in {secs} s (last answer: {last})"


def stage_engine(app_dir, licence):
    prof = profile(licence)
    proc, port = start_engine(app_dir, prof)
    t0 = time.time()
    try:
        h, problem = wait_health(proc, port, 120)
        return problem or f"answered in {time.time() - t0:.0f} s: {h.get('error') or 'ok'}"
    finally:
        kill_tree(proc.pid)
        time.sleep(1)
        if "Traceback" in engine_log(prof):
            print("   engine.log has a Traceback:\n" + engine_log(prof)[-1500:])
        drop_profile(prof)


def launch(exe, prof, store_pfn=""):
    """Start Lunar.exe the way a student's Windows does; returns the root PID."""
    if not store_pfn:
        return subprocess.Popen([exe, f"--user-data-dir={prof}"], cwd=os.path.dirname(exe), env=clean_env({}),
                                startupinfo=no_handles(), close_fds=True).pid
    before = set(processes())
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Invoke-CommandInDesktopPackage -PackageFamilyName '{store_pfn}' -AppId MrSOLIS "
                    f"-Command '{exe}' -Args '--user-data-dir={prof}'"], capture_output=True, check=True)
    for _ in range(40):
        procs = processes()
        for pid, (ppid, name) in procs.items():
            if pid not in before and name.lower() == "lunar.exe" and procs.get(ppid, (0, ""))[1].lower() != "lunar.exe":
                return pid
        time.sleep(0.5)
    raise RuntimeError("the package didn't start Lunar.exe")


def stage_first_launch(exe, licence, store_pfn=""):
    prof = profile(licence)
    root, t0, seen = launch(exe, prof, store_pfn), time.time(), set()
    try:
        while time.time() - t0 < 120:
            procs = tree(root)
            seen |= set(procs)
            titles = windows_of(procs)
            if ("lunar.exe", "Error") in titles:
                return "an error box ('Lunar could not start')"
            if ("lunar-backend.exe", "Unhandled exception in script") in titles:
                return "the engine crashed (Unhandled exception in script)"
            if ("lunar.exe", "Activate MrSOLIS") in titles:
                return "it asked for activation: the licence wasn't accepted (use one made for this computer)"
            if any(n == "lunar.exe" and t.startswith("MrSOLIS 3") for n, t in titles):
                took = time.time() - t0
                time.sleep(8)                               # the page settles; a late failure would show now
                if ("lunar.exe", "Error") in windows_of(tree(root)):
                    return "an error box after the window opened"
                log = engine_log(prof)
                if "Traceback" in log:
                    return "engine.log has a Traceback:\n" + log[-1500:]
                return f"the MrSOLIS window opened in {took:.0f} s" + ("" if log else " (engine.log missing!)")
            if not procs:
                return "Lunar.exe closed by itself"
            time.sleep(1)
        return "no MrSOLIS window in 120 s"
    finally:
        kill_tree(root, seen)
        time.sleep(1)
        drop_profile(prof)


def stage_brain(app_dir, licence, brains_from):
    """Returns (load problem, answer problem): the brain loads, then answers a real question."""
    prof = profile(licence, brains_from)
    proc, port = start_engine(app_dir, prof)
    try:
        t0 = time.time()
        h, problem = wait_health(proc, port, 300, lambda h: h.get("brain_state") in ("ready", "error"))
        if problem or h.get("brain_state") != "ready":
            return problem or f"brain {h.get('chat_model')}: {h.get('error')}", "skipped (no brain)"
        loaded = f"{h.get('chat_model')} ready in {time.time() - t0:.0f} s"
        t1, text, done = time.time(), "", False
        raw = get_json(port, "/api/chat_stream", timeout=300, body={"message": "What is 7 times 8? Answer briefly."})
        for line in raw.decode("utf-8", "replace").splitlines():
            msg = json.loads(line) if line.strip() else {}
            text += msg.get("token", "")
            done = done or bool(msg.get("done"))
            if msg.get("error"):
                return loaded, f"error: {msg['error']}"
        if not done or "56" not in text:
            return loaded, f"no proper answer: {text[:200]!r}"
        return loaded, f"answered in {time.time() - t1:.0f} s: {text.strip()[:120]!r}"
    finally:
        kill_tree(proc.pid)
        time.sleep(1)
        drop_profile(prof)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("package", help="Lunar-Setup-x.y.z.exe, or an unpacked app folder (the one with Lunar.exe)")
    ap.add_argument("--licence", required=True, help="a licence.json made for this computer")
    ap.add_argument("--brains", default="", help="a profile folder whose brains/ holds downloaded brains")
    ap.add_argument("--store", default="", help="PackageFamilyName of the registered Store package")
    ap.add_argument("--store-exe", default="", help="app\\Lunar.exe inside that registered package's folder")
    ap.add_argument("--work", default="", help="where throwaway profiles go (default: TEMP). For --store use a folder "
                    "outside AppData: a packaged app's writes under AppData may land in its own private copy")
    a = ap.parse_args()
    global WORK
    if a.work:
        os.makedirs(a.work, exist_ok=True)
        WORK = a.work
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # the engine's messages have "→" in them
    results, work = [], ""
    app_dir = a.package
    if a.package.lower().endswith(".exe"):
        work = tempfile.mkdtemp(prefix="mrsolis-smoke-app-")
        app_dir = work
        print("1. installer unpacks ...", flush=True)
        problem = unpack(a.package, app_dir)
        results.append(("installer unpacks", not problem, problem or "Lunar.exe, engine, app.asar"))
    try:
        if not os.path.isfile(os.path.join(app_dir, "Lunar.exe")):
            results.append(("app folder", False, f"no Lunar.exe in {app_dir}"))
        else:
            print("2. engine, no console ...", flush=True)
            r = stage_engine(app_dir, a.licence)
            results.append(("engine starts, no console", r.startswith("answered"), r))
            print("3. first launch, new student ...", flush=True)
            r = stage_first_launch(os.path.join(app_dir, "Lunar.exe"), a.licence)
            results.append(("first launch opens MrSOLIS", r.startswith("the MrSOLIS window opened"), r))
            if a.brains:
                print("4-5. brain loads and answers ...", flush=True)
                loaded, answered = stage_brain(app_dir, a.licence, a.brains)
                results.append(("brain loads", "ready in" in loaded, loaded))
                results.append(("answers a question", answered.startswith("answered"), answered))
        if a.store:
            print("6. Store package, first launch ...", flush=True)
            r = stage_first_launch(a.store_exe, a.licence, a.store)
            results.append(("Store package opens MrSOLIS", r.startswith("the MrSOLIS window opened"), r))
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
    print()
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:30} {detail}")
    bad = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - bad}/{len(results)} stages passed" + ("" if not bad else " — DO NOT RELEASE"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
