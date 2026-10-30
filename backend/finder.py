"""
Find the student's study files by name, anywhere sensible on this computer ("/find EE 172").

A background walk lists the document files (PDF, PowerPoint, Word, text) in the places
students keep them — Desktop, Downloads, Documents and OneDrive first, then the rest of
the home folder, other drives and USB sticks — skipping app data, code and media folders.
Searches answer from that list in memory (while it's still being built, from what's been
found so far), and the top of Desktop / Downloads / Documents is re-checked on every
search so a file downloaded a minute ago is found too. Nothing leaves the computer.

Only files a search has shown can be opened (`allowed`), so nothing else on the computer
can be read through the backend.
"""

import os
import re
import string
import sys
import threading
import time

KINDS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".txt"}
# folders that never hold a student's slides (case-insensitive); names starting with . $ ~ are skipped too
SKIP = {
    "appdata", "application data", "local settings", "node_modules", "__pycache__",
    "site-packages", "venv", "env", "bower_components", "music", "videos", "pictures", "movies",
    "my music", "my pictures", "my videos", "cookies", "nethood", "printhood", "recent", "sendto",
    "start menu", "templates", "windows", "program files", "program files (x86)", "programdata",
    "system volume information", "recovery", "perflogs", "msocache", "intel", "amd", "nvidia",
}
_HOME_SKIP = {"library"}       # macOS ~/Library (only at the top of the home folder)
_MAX_ENTRIES = 2_000_000
_MAX_SECONDS = 180
_STALE = 120                   # a list older than this is refreshed (in the background) on the next search

_files = {}                    # path -> (squashed name, words, name, folder words, mtime, size)
_built_at = 0.0
_building = False
_lock = threading.Lock()
_shown = set()                 # paths a search has returned: the only ones /api/files/open accepts


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _roots() -> list:
    home = os.path.expanduser("~")
    first = [os.path.join(home, n) for n in ("Desktop", "Downloads", "Documents")]
    first += [os.path.join(home, n) for n in sorted(os.listdir(home)) if n.lower().startswith("onedrive")] \
        if os.path.isdir(home) else []
    rest = [home]
    if sys.platform == "win32":
        system = (os.environ.get("SystemDrive") or "C:").upper().rstrip("\\")
        rest += [f"{d}:\\" for d in string.ascii_uppercase if f"{d}:" != system and os.path.exists(f"{d}:\\")]
    else:
        for base in ("/Volumes", "/media", "/mnt", "/run/media"):
            if os.path.isdir(base):
                rest += [os.path.join(base, n) for n in os.listdir(base)]
    return [r for r in first if os.path.isdir(r)] + rest


def _entry(path: str, name: str, st) -> tuple:
    stem = os.path.splitext(name)[0]
    folders = os.path.dirname(path).replace("\\", "/").split("/")[-2:]
    return (_squash(stem), re.findall(r"[a-z0-9]+", stem.lower()), name,
            re.findall(r"[a-z0-9]+", " ".join(folders).lower()), st.st_mtime, st.st_size)


def _scan_dir(path: str, found: dict, stack=None) -> int:
    """List one folder: documents go into `found`, subfolders onto `stack` (if given)."""
    n = 0
    at_home = os.path.normcase(path) == os.path.normcase(os.path.expanduser("~"))
    try:
        with os.scandir(path) as it:
            for e in it:
                n += 1
                name = e.name
                if name[:1] in ".$~" or name.lower() in SKIP or (at_home and name.lower() in _HOME_SKIP):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        if stack is not None and not (hasattr(e, "is_junction") and e.is_junction()):
                            stack.append(e.path)
                    elif os.path.splitext(name)[1].lower() in KINDS:
                        found[e.path] = _entry(e.path, name, e.stat())
                except OSError:
                    pass
    except OSError:
        pass
    return n


def _build():
    global _files, _built_at, _building
    fresh, seen, visited = {}, 0, set()
    deadline = time.time() + _MAX_SECONDS
    first, shared = not _built_at, time.time()
    try:
        for root in _roots():
            stack = [root]
            while stack and seen < _MAX_ENTRIES and time.time() < deadline:
                d = stack.pop()
                key = os.path.normcase(os.path.abspath(d))
                if key in visited:                     # Desktop etc. come up again under home
                    continue
                visited.add(key)
                seen += _scan_dir(d, fresh, stack)
                if first and time.time() - shared > 0.3:   # the very first list: share matches as they're found
                    with _lock:
                        _files.update(fresh)
                    shared = time.time()
        with _lock:
            _files = fresh
            _built_at = time.time()
    finally:
        _building = False


def refresh(wait: bool = False):
    """(Re)build the list in the background; `wait` blocks until a first list exists."""
    global _building
    with _lock:
        start = not _building
        _building = True
    if start:
        threading.Thread(target=_build, daemon=True, name="lunar-finder").start()
    if wait:
        for _ in range(40):                            # up to ~2 s for the first matches
            if _files or not _building:
                break
            time.sleep(0.05)


def status() -> dict:
    return {"files": len(_files), "building": _building, "age": time.time() - _built_at if _built_at else None}


def _quick_check():
    """New downloads: re-list the top of the likeliest folders (cheap) before every search."""
    home = os.path.expanduser("~")
    found = {}
    for n in ("Desktop", "Downloads", "Documents"):
        p = os.path.join(home, n)
        if os.path.isdir(p):
            _scan_dir(p, found)
    if found:
        with _lock:
            _files.update(found)


def search(query: str, limit: int = 20) -> list:
    tokens = re.findall(r"[a-z0-9]+", (query or "").lower())
    if not tokens:
        return []
    if not _built_at or time.time() - _built_at > _STALE:
        refresh(wait=not _files)
    _quick_check()
    home = os.path.expanduser("~")
    scored = []
    with _lock:
        items = list(_files.items())
    for path, (sq, words, name, folder_words, mtime, size) in items:
        folders = "".join(folder_words)
        if not all(t in sq or t in folders for t in tokens):
            continue
        # a token counts more where it starts a word of the file name ("EE" in "EE 172", not in "Meeting")
        starts, pos = set(), 0
        for w in words:
            starts.add(pos)
            pos += len(w)
        score = 0
        for t in tokens:
            i = sq.find(t)
            hits = set()
            while i != -1:
                hits.add(i)
                i = sq.find(t, i + 1)
            score += 3 if hits & starts else 1 if hits else 0
            score += 1 if any(w.startswith(t) for w in folder_words) else 0
        if _squash(query) == sq:
            score += 10                                # the exact name
        scored.append((score, mtime, path, name, size))
    scored.sort(key=lambda r: (-r[0], -r[1]))
    out = []
    for score, mtime, path, name, size in scored[:limit]:
        folder = os.path.dirname(path)
        shown = folder[len(home) + 1:] if folder.lower().startswith(home.lower() + os.sep) else folder
        out.append({"name": name, "path": path, "folder": shown.replace("\\", " › ").replace("/", " › ") or "Home",
                    "modified": mtime, "size": size})
        _shown.add(os.path.normcase(os.path.abspath(path)))
    return out


def allowed(path: str) -> bool:
    """Only a file a search has shown, of a kind MrSOLIS can teach, that's still there."""
    p = os.path.normcase(os.path.abspath(path or ""))
    return p in _shown and os.path.splitext(p)[1] in KINDS and os.path.isfile(path)
